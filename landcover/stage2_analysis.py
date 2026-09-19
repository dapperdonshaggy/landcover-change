"""
STAGE 2 — Statistics, change detection, and trend analysis.

Reads the aligned rasters produced by Stage 1 and produces:

    * per-year area statistics (CSV + bar charts)
    * a composite figure showing all years side by side
    * change detection maps between consecutive years
    * transition matrices and heatmaps
    * multi-year trend lines

Spatial logic notes
-------------------
- All rasters are assumed to share the same grid (Stage 1 guarantees this).
- Pixel values are treated as categorical class codes, not continuous
  measurements.
- A pixel is only compared across years if it holds a valid (non-NoData)
  class in every year. This prevents fake transitions caused by clouds,
  sensor gaps, or raster edges.
- Change between two years is encoded as ``from_class * 10 + to_class``,
  so a pixel that went from Farmland (4) to Built-Up (5) becomes 45.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

try:
    import seaborn as sns
    HAS_SEABORN = True
except ImportError:
    HAS_SEABORN = False

from .helpers import compute_pixel_area_ha


# =====================================================================
# Class definitions
# =====================================================================

def load_classes(csv_path: Path | str) -> Tuple[Dict[int, str], Dict[int, str]]:
    """
    Load class codes, names, and colors from a CSV file.

    The CSV must contain at least the columns ``code``, ``name``, and
    ``color``. Any additional columns are ignored.

    Parameters
    ----------
    csv_path : Path or str
        Path to the class definitions CSV.

    Returns
    -------
    names : dict
        Mapping ``{class_code: class_name}``.
    colors : dict
        Mapping ``{class_code: hex_color}``.

    Raises
    ------
    ValueError
        If any of the required columns is missing.
    """
    df = pd.read_csv(csv_path)

    for col in ("code", "name", "color"):
        if col not in df.columns:
            raise ValueError(f"classes.csv is missing column: {col}")

    names = dict(zip(df["code"], df["name"]))
    colors = dict(zip(df["code"], df["color"]))
    return names, colors


# =====================================================================
# Raster data container
# =====================================================================

class RasterData:
    """
    Holds aligned rasters, class info, and pixel metadata.

    This class is the single source of truth for the analysis stage.
    Every method that needs raster values or class areas reads from
    here, so pixel-area logic, NoData handling, and year parsing are
    defined in exactly one place.

    Attributes
    ----------
    years : list of str
        Sorted list of year strings (e.g. ``["1995", "2005", ...]``).
    data : dict
        ``{year: 2D numpy array}`` of class codes.
    pixel_area : dict
        ``{year: hectares per pixel}``.
    transforms : dict
        ``{year: affine transform}``.
    crs : dict
        ``{year: CRS}``.
    filenames : dict
        ``{year: original filename}``.
    names : dict
        ``{class_code: class_name}``.
    colors : dict
        ``{class_code: hex_color}``.
    """

    def __init__(self, settings: dict) -> None:
        self.settings = settings
        self.names: Dict[int, str] = {}
        self.colors: Dict[int, str] = {}
        self.years: List[str] = []
        self.data: Dict[str, np.ndarray] = {}
        self.transforms: Dict[str, object] = {}
        self.crs: Dict[str, object] = {}
        self.pixel_area: Dict[str, float] = {}
        self.filenames: Dict[str, str] = {}

    # ---------------------------------------------------------------- loading
    def load(self) -> None:
        """
        Load class definitions and all aligned rasters.

        Aligned rasters are discovered from ``settings["aligned_dir"]``
        by matching ``*_aligned.tif``. Each file's 4-digit year is
        extracted from its name. Pixel values that are not valid class
        codes are replaced with the configured NoData value.
        """
        print("\nLoading class definitions...")
        self.names, self.colors = load_classes(self.settings["class_csv"])
        print(f"  Loaded {len(self.names)} classes")

        print("\nLoading aligned rasters...")
        folder = self.settings["aligned_dir"]
        files = sorted(folder.glob("*_aligned.tif"))

        if not files:
            raise FileNotFoundError(
                f"No aligned rasters in {folder}\n"
                f"Did you run 'python run_alignment.py' first?"
            )

        nodata = self.settings["nodata"]
        valid_classes = list(self.names.keys())

        for path in files:
            year = self._extract_year(path.name)

            with rasterio.open(path) as src:
                raw = src.read(1)
                transform = src.transform
                crs = src.crs

            # Vectorized NoData masking: any pixel not in the class list
            # becomes NoData in a single operation.
            data = np.where(np.isin(raw, valid_classes), raw, nodata)

            self.years.append(year)
            self.data[year] = data
            self.transforms[year] = transform
            self.crs[year] = crs
            self.pixel_area[year] = compute_pixel_area_ha(transform)
            self.filenames[year] = path.name

            valid_count = int((data > nodata).sum())
            print(
                f"  ✓ {path.name} → year {year} "
                f"({valid_count:,} valid pixels)"
            )

        self.years = sorted(self.years)
        print(f"\nLoaded years: {self.years}")

    @staticmethod
    def _extract_year(filename: str) -> str:
        """
        Extract the first 4-digit year from a filename.

        Falls back to the first run of digits if no 4-digit year is
        found, then to the first underscore-separated token.
        """
        match = re.search(r"\d{4}", filename)
        if match:
            return match.group()
        numbers = re.findall(r"\d+", filename)
        return numbers[0] if numbers else filename.split("_")[0]

    # ---------------------------------------------------------------- queries
    def class_area(self, year: str, class_code: int) -> float:
        """
        Return the area (ha) covered by one class in one year.

        Vectorized: uses a NumPy boolean sum rather than Python loops
        over pixels.

        Parameters
        ----------
        year : str
            Year identifier.
        class_code : int
            Class code to count.

        Returns
        -------
        float
            Area in hectares.
        """
        pixels = int((self.data[year] == class_code).sum())
        return pixels * self.pixel_area[year]

    
    def class_counts(self, year: str) -> np.ndarray:
        """
        Return an array of pixel counts per class code for one year.

        Vectorized via ``np.bincount`` — a single pass over the data
        computes every class count at once.

        The returned array is indexed by class code: ``counts[c]`` is
        the number of pixels with value ``c``. Index 0 is NoData and
        should be ignored.

        Note: rasters are often stored as float32 even when values are
        whole numbers, so we cast to int16 before calling bincount
        (which requires integer input).

        Parameters
        ----------
        year : str
            Year identifier.

        Returns
        -------
        np.ndarray
            Pixel counts indexed by class code.
        """
        data = self.data[year]
        max_code = int(max(self.names.keys()))
        # Cast to int16 — class codes are small, and bincount needs ints
        ints = data.astype(np.int16).ravel()
        return np.bincount(ints, minlength=max_code + 1)


# =====================================================================
# Statistics and yearly bar graphs
# =====================================================================

def write_statistics_csv(rd: RasterData, output_dir: Path) -> Path:
    """
    Write a two-table CSV summarizing raster metadata and class areas.

    Table 1 lists one row per raster (dimensions, pixel area, CRS).
    Table 2 lists one row per year with per-class area in hectares.

    Parameters
    ----------
    rd : RasterData
        Loaded raster data.
    output_dir : Path
        Directory to write ``statistics.csv``.

    Returns
    -------
    Path
        Path to the written CSV.
    """
    print("\nWriting statistics CSV...")
    lines = []

    # Table 1
    lines.append("TABLE 1: RASTER FILE INFORMATION")
    lines.append("Year,Filename,Width,Height,PixelArea_ha,CRS")
    for year in rd.years:
        arr = rd.data[year]
        lines.append(
            f"{year},{rd.filenames[year]},{arr.shape[1]},{arr.shape[0]},"
            f"{rd.pixel_area[year]:.4f},{rd.crs[year]}"
        )

    # Table 2
    lines.append("")
    lines.append("TABLE 2: CLASS AREA PER YEAR (hectares)")

    codes = sorted(rd.names)
    header = ["Year", "Total"] + [rd.names[c] for c in codes]
    lines.append(",".join(header))

    for year in rd.years:
        counts = rd.class_counts(year)
        pixel_area = rd.pixel_area[year]

        row = [year]
        areas = [counts[c] * pixel_area for c in codes]
        row.append(f"{sum(areas):.0f}")
        row.extend(f"{a:.0f}" for a in areas)
        lines.append(",".join(row))

    out = output_dir / "statistics.csv"
    out.write_text("\n".join(lines))
    print(f"  Saved: {out}")
    return out


def make_yearly_bar_graphs(rd: RasterData, output_dir: Path, dpi: int) -> Path:
    """
    Create yearly bar graphs.

    Produces one standalone PNG per year, plus a single composite
    figure arranging all years in a grid (2 columns).

    All class areas are computed via ``rd.class_counts`` which uses
    ``np.bincount`` — a single vectorized pass over each raster.

    Parameters
    ----------
    rd : RasterData
        Loaded raster data.
    output_dir : Path
        Root output directory; graphs go into ``yearly_graphs/``.
    dpi : int
        Resolution for saved figures.

    Returns
    -------
    Path
        Path to the ``yearly_graphs`` folder.
    """
    print("\nCreating yearly bar graphs...")
    folder = output_dir / "yearly_graphs"
    folder.mkdir(parents=True, exist_ok=True)

    codes = sorted(rd.names)
    labels = [rd.names[c] for c in codes]
    colors = [rd.colors[c] for c in codes]

    
    # Precompute areas per year in one vectorized pass each
    areas_by_year: Dict[str, List[float]] = {}
    for year in rd.years:
        counts = rd.class_counts(year)
        pixel_area = rd.pixel_area[year]
        areas_by_year[year] = [counts[c] * pixel_area for c in codes]

    # --- Individual graphs ---
    for year in rd.years:
        areas = areas_by_year[year]

        # Calculate percentages
        total_area = sum(areas)
        percentages = [(area/total_area)*100 for area in areas]
            
        fig, ax = plt.subplots(figsize=(12, 7))
        bars = ax.bar(labels, areas, color=colors,
                      edgecolor="black", linewidth=0.5)

        ax.set_title(f"Land Cover Area — {year}",
                     fontsize=15, fontweight="bold")
        ax.set_ylabel("Area (hectares)")
        ax.tick_params(axis="x", rotation=45)
        ax.grid(axis="y", alpha=0.3, linestyle="--")

        for bar, area, pct in zip(bars, areas, percentages):
            if area > 0:
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() * 1.01,
                        f"{area:,.0f}\n({pct:.2f}%)",
                        ha="center", va="bottom", fontsize=9)

        plt.tight_layout()
        plt.savefig(folder / f"bar_graph_{year}.png",
                    dpi=dpi, bbox_inches="tight")
        plt.close()
        print(f"  ✓ {year}")

    # --- Composite figure ---
    print("  Creating composite figure...")
    n_years = len(rd.years)
    n_cols = 2
    n_rows = (n_years + n_cols - 1) // n_cols

    fig, axes = plt.subplots(n_rows, n_cols,
                             figsize=(n_cols * 8, n_rows * 6))
    axes = np.atleast_1d(axes).flatten()

    for idx, year in enumerate(rd.years):
        ax = axes[idx]
        areas = areas_by_year[year]

        bars = ax.bar(labels, areas, color=colors,
                      edgecolor="black", linewidth=0.5, alpha=0.9)

        ax.set_title(f"Land Cover Area — {year}",
                     fontsize=14, fontweight="bold", pad=12)
        ax.set_ylabel("Area (hectares)", fontsize=11)
        ax.tick_params(axis="x", rotation=45, labelsize=9)
        ax.grid(axis="y", alpha=0.3, linestyle="--")

        for bar, area, pct in zip(bars, areas, percentages):
            if area > 0:
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() * 1.01,
                        f"{area:,.0f}\n({pct:.2f}%)",
                        ha="center", va="bottom",
                        fontsize=8, fontweight="bold")

    for idx in range(n_years, len(axes)):
        fig.delaxes(axes[idx])

    plt.suptitle("Land Cover Area Distribution by Year",
                 fontsize=17, fontweight="bold", y=0.99)
    plt.tight_layout(rect=[0, 0, 1, 0.97])

    composite_path = folder / "all_years_composite.png"
    plt.savefig(composite_path, dpi=dpi, bbox_inches="tight")
    plt.close()
    print(f"  ✓ Composite figure saved: {composite_path}")
    print(f"  All graphs saved in: {folder}")
    return folder


# =====================================================================
# Change detection
# =====================================================================

def detect_change_between(
    rd: RasterData,
    year1: str,
    year2: str,
    output_dir: Path,
    nodata: int,
    dpi: int,
) -> None:
    """
    Compare two consecutive years and write all change outputs.

    Spatial logic
    -------------
    1. Only pixels that are valid (non-NoData) in BOTH years are
       compared. This prevents fake changes at cloud edges, sensor
       gaps, or raster boundaries.
    2. Change is encoded as ``from_class * 10 + to_class`` so a single
       integer captures both source and destination. For example, a
       pixel going from Grassland (3) to Farmland (4) is stored as 34.
    3. Statistics are computed with ``np.bincount`` in one pass over
       the change matrix, which is much faster than looping over every
       possible (from, to) pair.

    Outputs
    -------
    In ``output_dir``:
        * ``change_map_<y1>_<y2>.tif`` — GeoTIFF of encoded transitions
        * ``change_stats_<y1>_<y2>.csv`` — per-transition statistics
        * ``transition_area_<y1>_<y2>.csv`` — area matrix
        * ``transition_percent_<y1>_<y2>.csv`` — percentage matrix
        * ``heatmap_<y1>_<y2>.png`` — heatmap of the percentage matrix
        * ``comparison_<y1>_<y2>.png`` — side-by-side land cover maps

    Parameters
    ----------
    rd : RasterData
        Loaded raster data.
    year1, year2 : str
        The two years to compare.
    output_dir : Path
        Directory for outputs.
    nodata : int
        Value representing NoData.
    dpi : int
        Resolution for saved figures.
    """
    print(f"\n  Analyzing change: {year1} → {year2}")

    data1 = rd.data[year1]
    data2 = rd.data[year2]
    pixel_area = rd.pixel_area[year1]

    # Valid only where both years have real class values
    valid = (data1 > nodata) & (data2 > nodata)

    # Encode change as from * 10 + to
    change = np.zeros_like(data1)
    change[valid] = data1[valid] * 10 + data2[valid]

    # ---------------------------------------------------------------
    # Save GeoTIFF
    # ---------------------------------------------------------------
    profile = {
        "driver": "GTiff",
        "height": change.shape[0],
        "width": change.shape[1],
        "count": 1,
        "dtype": "uint8",
        "crs": rd.crs[year1],
        "transform": rd.transforms[year1],
        "nodata": 0,
        "compress": "lzw",
    }
    tif_path = output_dir / f"change_map_{year1}_{year2}.tif"
    with rasterio.open(tif_path, "w", **profile) as dst:
        dst.write(change.astype("uint8"), 1)
    print(f"    Saved: {tif_path.name}")

    # ---------------------------------------------------------------
    # Vectorized statistics
    # ---------------------------------------------------------------
    class_ids = sorted(rd.names)
    total_valid = int((change > 0).sum())

    # Single-pass count of every change code.
    # Cast to int16 first — bincount requires integer input.
    flat = change.astype(np.int16).ravel()
    counts = np.bincount(flat)

    n_classes = len(class_ids)
    matrix_area = np.zeros((n_classes, n_classes))
    matrix_pct = np.zeros((n_classes, n_classes))
    rows = []

    for i, fc in enumerate(class_ids):
        for j, tc in enumerate(class_ids):
            code = fc * 10 + tc
            count = int(counts[code]) if code < len(counts) else 0
            area = count * pixel_area
            pct = (count / total_valid * 100) if total_valid else 0

            matrix_area[i, j] = area
            matrix_pct[i, j] = pct

            rows.append({
                "From": rd.names[fc],
                "To": rd.names[tc],
                "Pixels": count,
                "Area_ha": area,
                "Percent": pct,
            })
    stats_df = pd.DataFrame(rows)
    csv_path = output_dir / f"change_stats_{year1}_{year2}.csv"
    stats_df.to_csv(csv_path, index=False)
    print(f"    Saved: {csv_path.name}")

    # ---------------------------------------------------------------
    # Transition matrices
    # ---------------------------------------------------------------
    labels = [rd.names[c] for c in class_ids]
    pd.DataFrame(matrix_area, index=labels, columns=labels).to_csv(
        output_dir / f"transition_area_{year1}_{year2}.csv"
    )
    pd.DataFrame(matrix_pct, index=labels, columns=labels).to_csv(
        output_dir / f"transition_percent_{year1}_{year2}.csv"
    )

    # ---------------------------------------------------------------
    # Heatmap
    # ---------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(12, 10))
    if HAS_SEABORN:
        sns.heatmap(matrix_pct, annot=True, fmt=".1f", cmap="YlOrRd",
                    xticklabels=labels, yticklabels=labels,
                    linewidths=0.5, linecolor="gray", ax=ax)
    else:
        im = ax.imshow(matrix_pct, cmap="YlOrRd", aspect="auto")
        plt.colorbar(im, ax=ax)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels)
        for i in range(len(labels)):
            for j in range(len(labels)):
                if matrix_pct[i, j] > 0:
                    ax.text(j, i, f"{matrix_pct[i, j]:.1f}",
                            ha="center", va="center", fontsize=8)

    ax.set_title(f"Transition Matrix: {year1} → {year2}\n"
                 f"(% of total valid area)",
                 fontsize=14, fontweight="bold")
    ax.set_xlabel("To Class")
    ax.set_ylabel("From Class")
    plt.tight_layout()
    plt.savefig(output_dir / f"heatmap_{year1}_{year2}.png",
                dpi=dpi, bbox_inches="tight")
    plt.close()
    print(f"    Saved: heatmap_{year1}_{year2}.png")

    # ---------------------------------------------------------------
    # Side-by-side comparison
    # ---------------------------------------------------------------
    class_colors = [rd.colors[c] for c in sorted(rd.names)]
    cmap = ListedColormap(class_colors)

    fig, axes = plt.subplots(1, 2, figsize=(18, 8))
    for ax_, year, d in zip(axes, [year1, year2], [data1, data2]):
        ax_.imshow(np.ma.masked_where(d == nodata, d),
                   cmap=cmap, interpolation="nearest")
        ax_.set_title(f"{year} Land Cover", fontsize=14,
                      fontweight="bold")
        ax_.axis("off")

    legend = [Patch(facecolor=rd.colors[c], label=rd.names[c])
              for c in sorted(rd.names)]
    axes[1].legend(handles=legend, loc="upper right",
                   fontsize=8, framealpha=0.9)

    plt.tight_layout()
    plt.savefig(output_dir / f"comparison_{year1}_{year2}.png",
                dpi=dpi, bbox_inches="tight")
    plt.close()


def run_change_detection(
    rd: RasterData, output_dir: Path, nodata: int, dpi: int
) -> None:
    """
    Run change detection for every consecutive pair of years.

    Parameters
    ----------
    rd : RasterData
        Loaded raster data.
    output_dir : Path
        Root output directory; results go into ``change_detection/``.
    nodata : int
        Value representing NoData.
    dpi : int
        Resolution for saved figures.
    """
    print("\nRunning change detection...")
    folder = output_dir / "change_detection"
    folder.mkdir(parents=True, exist_ok=True)

    years = rd.years
    for i in range(len(years) - 1):
        detect_change_between(rd, years[i], years[i + 1],
                              folder, nodata, dpi)


# =====================================================================
# Trend analysis
# =====================================================================

def run_trend_analysis(rd: RasterData, output_dir: Path, dpi: int) -> Path:
    """
    Create multi-year trend lines for each class.

    Produces:
        * ``trend_area.png`` — hectares per class over time, with
          value labels on every data point
        * ``trend_percentage.png`` — percentage of total area per
          class over time, with value labels on every data point
        * ``trend_data.csv`` — the underlying numbers

    All class areas are computed via ``rd.class_counts`` (single-pass
    ``np.bincount``) rather than per-class boolean sums.

    Parameters
    ----------
    rd : RasterData
        Loaded raster data.
    output_dir : Path
        Root output directory; results go into ``trend_analysis/``.
    dpi : int
        Resolution for saved figures.

    Returns
    -------
    Path
        Path to the ``trend_analysis`` folder.
    """
    print("\nRunning trend analysis...")
    folder = output_dir / "trend_analysis"
    folder.mkdir(parents=True, exist_ok=True)

    years = rd.years
    codes = sorted(rd.names)

    # Vectorized data collection — one bincount per year
    areas: Dict[int, List[float]] = {c: [] for c in codes}
    pcts: Dict[int, List[float]] = {c: [] for c in codes}

    for year in years:
        counts = rd.class_counts(year)
        pixel_area = rd.pixel_area[year]
        year_areas = {c: counts[c] * pixel_area for c in codes}
        total = sum(year_areas.values())
        for c in codes:
            areas[c].append(year_areas[c])
            pcts[c].append((year_areas[c] / total * 100) if total else 0)

    # ---------------------------------------------------------------
    # Area trend with labels
    # ---------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(15, 9))
    for c in codes:
        ax.plot(years, areas[c], marker="o", linewidth=2.5,
                markersize=9, label=rd.names[c], color=rd.colors[c])
        for x, y in zip(years, areas[c]):
            if y > 0:
                ax.annotate(
                    f"{y:,.0f}",
                    (x, y),
                    textcoords="offset points",
                    xytext=(0, 10),
                    ha="center", va="bottom",
                    fontsize=8, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2",
                              facecolor="white", alpha=0.75,
                              edgecolor="none"),
                )

    ax.set_title("Land Cover Area Trends (hectares)",
                 fontsize=15, fontweight="bold")
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Area (hectares)", fontsize=12)
    ax.legend(bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=10)
    ax.grid(True, alpha=0.3, linestyle="--")
    plt.tight_layout()
    plt.savefig(folder / "trend_area.png", dpi=dpi, bbox_inches="tight")
    plt.close()

    # ---------------------------------------------------------------
    # Percentage trend with labels
    # ---------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(15, 9))
    for c in codes:
        ax.plot(years, pcts[c], marker="s", linewidth=2.5,
                linestyle="--", markersize=9,
                label=rd.names[c], color=rd.colors[c])
        for x, y in zip(years, pcts[c]):
            if y > 0:
                ax.annotate(
                    f"{y:.1f}%",
                    (x, y),
                    textcoords="offset points",
                    xytext=(0, 10),
                    ha="center", va="bottom",
                    fontsize=8, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2",
                              facecolor="white", alpha=0.75,
                              edgecolor="none"),
                )

    ax.set_title("Land Cover Percentage Trends",
                 fontsize=15, fontweight="bold")
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Percentage of Total Area (%)", fontsize=12)
    ax.legend(bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=10)
    ax.grid(True, alpha=0.3, linestyle="--")
    plt.tight_layout()
    plt.savefig(folder / "trend_percentage.png",
                dpi=dpi, bbox_inches="tight")
    plt.close()

    # ---------------------------------------------------------------
    # CSV export
    # ---------------------------------------------------------------
    rows = []
    for i, year in enumerate(years):
        row = {"Year": year}
        for c in codes:
            name = rd.names[c].replace(" ", "_")
            row[f"{name}_ha"] = areas[c][i]
            row[f"{name}_pct"] = pcts[c][i]
        rows.append(row)
    pd.DataFrame(rows).to_csv(folder / "trend_data.csv", index=False)

    print(f"  Trend outputs saved in: {folder}")
    return folder


# =====================================================================
# Main entry
# =====================================================================

def run(settings: dict) -> None:
    """
    Run Stage 2: statistics, change detection, and trends.

    Parameters
    ----------
    settings : dict
        Loaded configuration dictionary (from ``config.load_config``).
    """
    print("=" * 60)
    print("STAGE 2: CHANGE DETECTION AND ANALYSIS")
    print("=" * 60)

    output_dir = settings["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    rd = RasterData(settings)
    rd.load()

    nodata = settings["nodata"]
    dpi = settings["figure_dpi"]

    write_statistics_csv(rd, output_dir)
    make_yearly_bar_graphs(rd, output_dir, dpi)
    run_change_detection(rd, output_dir, nodata, dpi)
    run_trend_analysis(rd, output_dir, dpi)

    print("\n" + "=" * 60)
    print("STAGE 2 COMPLETE")
    print(f"All results saved in: {output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    from .config import load_config
    run(load_config())