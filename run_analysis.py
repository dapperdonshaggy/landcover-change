"""
STEP 2 — Run this after run_alignment.py.

Reads the aligned rasters and produces statistics, change maps,
transition matrices, and trend graphs. Output goes to 'outputs/'.

Usage:
    python run_analysis.py
"""
from landcover.config import load_config
from landcover.stage2_analysis import run


if __name__ == "__main__":
    settings = load_config("config.yaml")
    run(settings)
    print("\nDone! Check the 'outputs/' folder for results.")