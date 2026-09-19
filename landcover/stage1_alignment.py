"""
STAGE 1 — Reproject and align raw rasters.

This stage takes raw classified rasters (which may be in different
coordinate systems, grids, or extents) and produces a set of rasters
that all share:
  - the same coordinate reference system (CRS)
  - the same pixel grid (transform, width, height)
  - the same NoData value

After this stage, pixel (row, col) refers to the same geographic
location in every raster — which is required for pixel-wise change
detection.
"""
from pathlib import Path
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject

from .helpers import find_rasters


def reproject_raster(input_path, output_path, target_crs, resampling, nodata):
    """
    Reproject a single raster to a target CRS.

    Why nearest-neighbour resampling?
    ---------------------------------
    Classified rasters hold class codes (1, 2, 3...). If we averaged
    neighboring pixels we could get values that don't correspond to any
    real class (e.g. average of class 2 and class 4 = class 3). Nearest
    resampling preserves the original class values.
    """
    try:
        with rasterio.open(input_path) as src:
            if src.crs is None:
                raise ValueError("Source raster has no CRS")

            # Compute the output grid size and transform
            transform, width, height = calculate_default_transform(
                src.crs, target_crs, src.width, src.height, *src.bounds
            )

            profile = src.profile.copy()
            profile.update(
                crs=target_crs,
                transform=transform,
                width=width,
                height=height,
                compress="lzw",
                nodata=nodata,
            )

            dst_data = np.zeros((height, width), dtype=src.dtypes[0])

            reproject(
                source=rasterio.band(src, 1),
                destination=dst_data,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=transform,
                dst_crs=target_crs,
                resampling=resampling,
                nodata=nodata,
            )

            with rasterio.open(output_path, "w", **profile) as dst:
                dst.write(dst_data, 1)

        return True

    except Exception as e:
        print(f"  Error reprojecting {Path(input_path).name}: {e}")
        return False


def align_raster(reference_path, source_path, output_path, resampling, nodata):
    """
    Align a source raster to a reference raster's grid.

    Two rasters can be in the same CRS but still have different grids
    (different origins or extents). This function forces the source
    onto the reference's transform, width, and height so that pixels
    line up exactly.
    """
    try:
        with rasterio.open(reference_path) as ref, \
             rasterio.open(source_path) as src:

            if ref.crs != src.crs:
                raise ValueError(
                    f"CRS mismatch: reference={ref.crs}, source={src.crs}"
                )

            profile = ref.profile.copy()
            profile.update(dtype=src.dtypes[0], nodata=nodata)

            aligned = np.full(
                (ref.height, ref.width),
                fill_value=nodata,
                dtype=src.dtypes[0],
            )

            reproject(
                source=rasterio.band(src, 1),
                destination=aligned,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=ref.transform,
                dst_crs=ref.crs,
                resampling=resampling,
                nodata=nodata,
            )

            with rasterio.open(output_path, "w", **profile) as dst:
                dst.write(aligned, 1)

        return True

    except Exception as e:
        print(f"  Error aligning {Path(source_path).name}: {e}")
        return False


def build_common_mask(aligned_files, output_path, nodata):
    """
    Build one mask showing pixels that are valid (non-NoData)
    in EVERY aligned raster.

    This is used by Stage 2 to make sure we only compare pixels that
    have real data in all years — avoiding fake 'changes' caused by
    clouds, sensor gaps, or raster edges.
    """
    if len(aligned_files) < 2:
        print("  Need at least 2 rasters for a common mask")
        return None

    arrays = []
    profile = None
    for path in aligned_files:
        with rasterio.open(path) as src:
            arrays.append(src.read(1))
            if profile is None:
                profile = src.profile.copy()

    # Stack into one 3D array: (n_years, height, width)
    stack = np.stack(arrays, axis=0)

    # A pixel is valid only if it's non-NoData in every year
    valid_stack = stack != nodata
    common_mask = np.all(valid_stack, axis=0)

    total = common_mask.size
    valid = int(common_mask.sum())
    print(f"  Mask coverage: {valid / total * 100:.1f}% "
          f"({valid:,} of {total:,} pixels valid in all years)")

    profile.update(dtype="uint8", count=1, nodata=0, compress="lzw")
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(common_mask.astype("uint8"), 1)

    return output_path


def run(settings):
    """
    Run Stage 1: reproject, align, and build common mask.
    """
    print("=" * 60)
    print("STAGE 1: REPROJECTION AND ALIGNMENT")
    print("=" * 60)

    input_dir = settings["input_dir"]
    aligned_dir = settings["aligned_dir"]
    target_crs = CRS.from_epsg(settings["target_epsg"])
    resampling = Resampling[settings["resampling"]]
    nodata = settings["nodata"]

    # Create output folder if it doesn't exist
    aligned_dir.mkdir(parents=True, exist_ok=True)

    # ---- 1. Find input files ----------------------------------------
    print(f"\nLooking for rasters in: {input_dir}")
    input_files = find_rasters(input_dir, settings["file_pattern"])

    if not input_files:
        raise FileNotFoundError(
            f"No raster files found in {input_dir}\n"
            f"Make sure your .tif files are in the 'raw_rasters' folder."
        )

    print(f"Found {len(input_files)} files:")
    for f in input_files:
        print(f"  - {f.name}")

    # ---- 2. Reproject every file ------------------------------------
    print(f"\nReprojecting to EPSG:{settings['target_epsg']}...")
    reprojected = []

    for src in input_files:
        out = aligned_dir / f"{src.stem}_reprojected.tif"
        if reproject_raster(src, out, target_crs, resampling, nodata):
            reprojected.append(out)
            print(f"  ✓ {src.name} → {out.name}")

    if not reprojected:
        raise RuntimeError("No files were successfully reprojected")

    # ---- 3. Align every file to the first one -----------------------
    print(f"\nAligning {len(reprojected)} rasters to reference grid...")
    reference = reprojected[0]
    print(f"Reference: {reference.name}")

    aligned = []
    for src in reprojected:
        # Strip "_reprojected" so name becomes e.g. "EWC_1995_aligned.tif"
        stem = src.stem.replace("_reprojected", "")
        out = aligned_dir / f"{stem}_aligned.tif"
        if align_raster(reference, src, out, resampling, nodata):
            aligned.append(out)
            print(f"  ✓ {out.name}")

    # ---- 4. Build the common mask -----------------------------------
    print("\nBuilding common valid-pixel mask...")
    mask_path = aligned_dir / "common_valid_mask.tif"
    build_common_mask(aligned, mask_path, nodata)

    print("\n" + "=" * 60)
    print(f"STAGE 1 COMPLETE — {len(aligned)} aligned rasters saved")
    print(f"Output folder: {aligned_dir}")
    print("=" * 60)


if __name__ == "__main__":
    from .config import load_config
    run(load_config())