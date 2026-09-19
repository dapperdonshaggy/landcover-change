"""
Shared I/O helpers for raster operations.

This module centralizes the small, reusable operations that both
pipeline stages depend on:

    * reading a raster band and its metadata
    * computing pixel area in hectares from an affine transform
    * discovering valid GeoTIFF files in a folder

Keeping these here means both stages share *identical* spatial logic.
If you ever need to change how pixel area is calculated, there is
exactly one place to change it.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import numpy as np
import rasterio
from affine import Affine


def compute_pixel_area_ha(transform: Affine) -> float:
    """
    Compute the area of one pixel in hectares.

    Spatial logic
    -------------
    An Affine transform describes how a raster's pixel coordinates map
    to world coordinates. For a north-up raster (the standard case for
    satellite imagery), the two diagonal components carry the pixel
    size in map units:

        transform.a  ->  pixel width  (x-resolution, in metres)
        transform.e  ->  pixel height (y-resolution, *negative* metres)

    The sign of ``e`` is negative because image rows increase downward
    while world Y increases upward. We take the absolute value.

    For a raster in a projected CRS (like UTM), the map units are
    metres. So:

        pixel_area_m2 = |a| * |e|
        pixel_area_ha = pixel_area_m2 / 10_000

    Note: this is only valid for rasters in a projected CRS. For
    geographic coordinates (EPSG:4326), pixel area varies with
    latitude and this function would give incorrect results.

    Parameters
    ----------
    transform : Affine
        The raster's affine transform, from ``rasterio.open(...).transform``.

    Returns
    -------
    float
        Area of one pixel in hectares.
    """
    pixel_width_m = abs(transform.a)
    pixel_height_m = abs(transform.e)
    return (pixel_width_m * pixel_height_m) / 10_000.0


def read_raster(
    path: Path | str,
    band: int = 1,
) -> Tuple[np.ndarray, dict]:
    """
    Read a single band from a raster file along with its metadata.

    Parameters
    ----------
    path : Path or str
        Path to the raster file.
    band : int, default 1
        Band index (1-based, following rasterio's convention).

    Returns
    -------
    data : np.ndarray
        2D array of raster values for the requested band.
    profile : dict
        Rasterio profile dict containing driver, dtype, transform,
        crs, nodata, width, height, etc.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    rasterio.errors.RasterioIOError
        If the file exists but cannot be opened as a raster.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Raster not found: {path}")

    with rasterio.open(path) as src:
        data = src.read(band)
        profile = src.profile.copy()

    return data, profile


def find_rasters(
    folder: Path | str,
    pattern: str = "*.tif",
) -> List[Path]:
    """
    Discover all valid raster files in a folder.

    A file is considered valid if rasterio can open it. Files that
    exist but fail to open (corrupt, wrong format, unreadable) are
    skipped with a warning instead of crashing the pipeline.

    Parameters
    ----------
    folder : Path or str
        Directory to search.
    pattern : str, default "*.tif"
        Glob pattern for candidate files.

    Returns
    -------
    list of Path
        Sorted list of valid raster file paths.
    """
    folder = Path(folder)
    files = sorted(folder.glob(pattern))

    valid: List[Path] = []
    for path in files:
        try:
            with rasterio.open(path):
                valid.append(path)
        except Exception as exc:
            print(f"  Skipping {path.name}: {exc}")

    return valid