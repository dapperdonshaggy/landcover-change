"""
STEP 1 — Run this first.

Reprojects and aligns all raw rasters in 'raw_rasters/' so that
they share the same grid. Output goes to 'aligned_rasters/'.

Usage:
    python run_alignment.py
"""
from landcover.config import load_config
from landcover.stage1_alignment import run


if __name__ == "__main__":
    settings = load_config("config.yaml")
    run(settings)
    print("\nNext step: run 'python run_analysis.py'")