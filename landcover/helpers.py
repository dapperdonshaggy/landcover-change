"""
Small shared helper functions used by both stages.
"""
from pathlib import Path
import numpy as np
import rasterio


def pixel_area_hectares(transform):
    """
    Calculate the area of one pixel in hectares.

    Rasters in a projected CRS (like UTM) have pixel sizes in meters.
    We multiply width by height to get square meters, then divide by
    10,000 to convert to hectares.
    """
    width_m = abs(transform.a)
    height_m = abs(transform.e)
    return (width_m * height_m) / 10_000


def read_raster(path):
    """Read band 1 and the profile of a raster."""
    with rasterio.open(path) as src:
        data = src.read(1)
        profile = src.profile.copy()
    return data, profile


def find_rasters(folder, pattern):
    """
    Find all raster files in a folder matching a pattern.
    Returns a sorted list of Path objects.
    """
    folder = Path(folder)
    files = sorted(folder.glob(pattern))

    valid = []
    for path in files:
        try:
            with rasterio.open(path):
                valid.append(path)
        except Exception as e:
            print(f"  Skipping {path.name}: {e}")
    return valid