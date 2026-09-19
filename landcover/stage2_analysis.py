"""
STAGE 2 — Statistics, change detection, and trend analysis.

Reads the aligned rasters produced by Stage 1 and produces:
  - Per-year area statistics (CSV + bar graphs)
  - Change detection maps between consecutive years
  - Transition matrices and heatmaps
  - Multi-year trend lines
"""
import re
from pathlib import Path

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

from .helpers import pixel_area_hectares


# =====================================================================
# Class definitions
# =====================================================================

def load_classes(csv_path):
    """Load class codes, names, and colors from CSV."""
    df = pd.read_csv(csv_path)
    for col in ("code", "name", "color"):
        if col not in df.columns:
            raise ValueError(f"classes.csv is missing column: {col}")

    names = dict(zip(df["code"], df["name"]))
    colors = dict(zip(df["code"], df["color"]))
    return names, colors


# =====================================================================
# Load aligned rasters
# =====================================================================

class RasterData:
    """Holds aligned rasters, class info, and pixel metadata."""

    def __init__(self, settings):
        self.settings = settings
        self.names = {}
        self.colors = {}
        self.years = []          # sorted list of year strings
        self.data = {}           # year -> 2D array
        self.transforms = {}     # year -> transform
        self.crs = {}            # year -> CRS
        self.pixel_area = {}     # year -> ha per pixel
        self.filenames = {}      # year -> filename

    def load(self):
        """Load classes then all aligned rasters."""
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

            # Zero out any pixel that isn't a valid class code
            data = np.where(np.isin(raw, valid_classes), raw, nodata)

            self.years.append(year)
            self.data[year] = data
            self.transforms[year] = transform
            self.crs[year] = crs
            self.pixel_area[year] = pixel_area_hectares(transform)
            self.filenames[year] = path.name

            valid_count = int((data > nodata).sum())
            print(f"  ✓ {path.name} → year {year} "
                  f"({valid_count:,} valid pixels)")

        self.years = sorted(self.years)
        print(f"\nLoaded years: {self.years}")

    def _extract_year(self, filename):
        """Pull the first 4-digit year from a filename."""
        match = re.search(self.settings["year_pattern"], filename)
        if match:
            return match.group()
        numbers = re.findall(r"\d+", filename)
        return numbers[0] if numbers else filename

    def class_area(self, year, class_code):
        """Return area (ha) of one class in one year."""
        pixels = int((self.data[year] == class_code).sum())
        return pixels * self.pixel_area[year]


# =====================================================================
# Statistics and yearly bar graphs
# =====================================================================

def write_statistics_csv(rd, output_dir):
    """Write a two-table CSV with file info and per-year class areas."""
    print("\nWriting statistics CSV...")
    lines = []

    # Table 1: file info
    lines.append("TABLE 1: RASTER FILE INFORMATION")
    lines.append("Year,Filename,Width,Height,PixelArea_ha,CRS")
    for year in rd.years:
        arr = rd.data[year]
        lines.append(
            f"{year},{rd.filenames[year]},{arr.shape[1]},{arr.shape[0]},"
            f"{rd.pixel_area[year]:.4f},{rd.crs[year]}"
        )

    lines.append("")
    lines.append("TABLE 2: CLASS AREA PER YEAR (hectares)")

    header = ["Year", "Total"]
    for code in sorted(rd.names):
        header.append(rd.names[code])
    lines.append(",".join(header))

    for year in rd.years:
        row = [year]
        total = sum(rd.class_area(year, c) for c in rd.names)
        row.append(f"{total:.0f}")
        for code in sorted(rd.names):
            row.append(f"{rd.class_area(year, code):.0f}")
        lines.append(",".join(row))

    out = output_dir / "statistics.csv"
    out.write_text("\n".join(lines))
    print(f"  Saved: {out}")


def make_yearly_bar_graphs(rd, output_dir, dpi):
    """
    Create yearly bar graphs:
      - One standalone graph per year
      - One composite figure showing all years in a grid (2x2 for 4 years)
    """
    print("\nCreating yearly bar graphs...")
    folder = output_dir / "yearly_graphs"
    folder.mkdir(parents=True, exist_ok=True)

    codes = sorted(rd.names)
    labels = [rd.names[c] for c in codes]
    colors = [rd.colors[c] for c in codes]

    # ---------------------------------------------------------------
    # 1. Individual bar graph per year (standalone files)
    # ---------------------------------------------------------------
    for year in rd.years:
        areas = [rd.class_area(year, c) for c in codes]

        fig, ax = plt.subplots(figsize=(12, 7))
        bars = ax.bar(labels, areas, color=colors,
                      edgecolor="black", linewidth=0.5)

        ax.set_title(f"Land Cover Area — {year}",
                     fontsize=15, fontweight="bold")
        ax.set_ylabel("Area (hectares)")
        ax.tick_params(axis="x", rotation=45)
        ax.grid(axis="y", alpha=0.3, linestyle="--")

        for bar, area in zip(bars, areas):
            if area > 0:
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() * 1.01,
                        f"{area:,.0f}",
                        ha="center", va="bottom", fontsize=9)

        plt.tight_layout()
        plt.savefig(folder / f"bar_graph_{year}.png",
                    dpi=dpi, bbox_inches="tight")
        plt.close()
        print(f"  ✓ {year}")

    # ---------------------------------------------------------------
    # 2. Composite figure — all years in a grid of subplots
    # ---------------------------------------------------------------
    print("  Creating composite figure...")

    n_years = len(rd.years)
    n_cols = 2                      # 2 columns
    n_rows = (n_years + 1) // 2     # ceil(n_years / 2)

    fig, axes = plt.subplots(n_rows, n_cols,
                             figsize=(n_cols * 8, n_rows * 6))
    # Flatten so we can iterate simply; also handles n_years == 1
    axes = np.atleast_1d(axes).flatten()

    for idx, year in enumerate(rd.years):
        ax = axes[idx]
        areas = [rd.class_area(year, c) for c in codes]
        total_area = sum(areas)
        percentages = [(area/total_area)*100 for area in areas]

        bars = ax.bar(labels, areas, color=colors,
                      edgecolor="black", linewidth=0.5, alpha=0.9)

        ax.set_title(f"Land Cover Area — {year}",
                     fontsize=14, fontweight="bold", pad=12)
        ax.set_ylabel("Area (hectares)", fontsize=11)
        ax.tick_params(axis="x", rotation=45, labelsize=9)
        ax.grid(axis="y", alpha=0.3, linestyle="--")

        # Value labels on top of each bar
        for bar, area, pct in zip(bars, areas, percentages):
            if area > 0:
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() * 1.01,
                        f"{area:,.0f} ha\n({pct:.2f}%) ",
                        ha="center", va="bottom",
                        fontsize=11, fontweight="bold")

    # Hide any empty subplot slots (only matters if n_years is odd)
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

# =====================================================================
# Change detection
# =====================================================================

def detect_change_between(rd, year1, year2, output_dir, nodata, dpi):
    """
    Compare two consecutive years and produce:
      - a change map (GeoTIFF)
      - a visualization PNG
      - a transition matrix (CSV)
      - a heatmap PNG
      - a statistics CSV
    """
    print(f"\n  Analyzing change: {year1} → {year2}")

    data1 = rd.data[year1]
    data2 = rd.data[year2]
    pixel_area = rd.pixel_area[year1]

    # Only compare pixels valid in BOTH years
    valid = (data1 > nodata) & (data2 > nodata)

    # Encode change as from * 10 + to (e.g. 3→4 becomes 34)
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
    # Compute per-transition statistics
    # ---------------------------------------------------------------
    class_ids = sorted(rd.names)
    total_valid = int((change > 0).sum())

    rows = []
    matrix_area = np.zeros((len(class_ids), len(class_ids)))
    matrix_pct = np.zeros((len(class_ids), len(class_ids)))

    for i, fc in enumerate(class_ids):
        for j, tc in enumerate(class_ids):
            code = fc * 10 + tc
            count = int((change == code).sum())
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
    # Transition matrix CSVs
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
    # Side-by-side visualization of the two years
    # ---------------------------------------------------------------
    colors = [rd.colors[c] for c in sorted(rd.names)]
    cmap = ListedColormap(colors)

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


def run_change_detection(rd, output_dir, nodata, dpi):
    """Run change detection for every consecutive year pair."""
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

def run_trend_analysis(rd, output_dir, dpi):
    """
    Create trend lines for each class across all years,
    with percentage labels on every data point.
    """
    print("\nRunning trend analysis...")
    folder = output_dir / "trend_analysis"
    folder.mkdir(parents=True, exist_ok=True)

    years = rd.years
    codes = sorted(rd.names)

    # Collect data
    areas = {c: [] for c in codes}
    pcts = {c: [] for c in codes}

    for year in years:
        total = sum(rd.class_area(year, c) for c in codes)
        for c in codes:
            a = rd.class_area(year, c)
            areas[c].append(a)
            pcts[c].append((a / total * 100) if total else 0)

    # ---------------------------------------------------------------
    # 1. Area trend line (hectares) with labels
    # ---------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(15, 9))
    for c in codes:
        ax.plot(years, areas[c], marker="o", linewidth=2.5,
                markersize=9, label=rd.names[c], color=rd.colors[c])

        # Add hectare label on each point
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
    plt.savefig(folder / "trend_area.png", dpi=dpi,
                bbox_inches="tight")
    plt.close()

    # ---------------------------------------------------------------
    # 2. Percentage trend line with labels
    # ---------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(15, 9))
    for c in codes:
        ax.plot(years, pcts[c], marker="s", linewidth=2.5,
                linestyle="--", markersize=9,
                label=rd.names[c], color=rd.colors[c])

        # Add percentage label on each point
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
    plt.savefig(folder / "trend_percentage.png", dpi=dpi,
                bbox_inches="tight")
    plt.close()

    # ---------------------------------------------------------------
    # 3. CSV export
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
# =====================================================================
# Main entry
# =====================================================================

def run(settings):
    """Run Stage 2: statistics, change detection, trends."""
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
    print(f"STAGE 2 COMPLETE")
    print(f"All results saved in: {output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    from .config import load_config
    run(load_config())