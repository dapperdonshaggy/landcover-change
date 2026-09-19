# Land Cover Change Detection

A two-stage geospatial pipeline for detecting and quantifying land cover
change across multiple years using aligned raster data.

## What It Does

The pipeline runs in two stages:

**Stage 1 — Alignment**
Reprojects raw classified rasters to a common coordinate reference
system and snaps them to a single pixel grid. After this stage, every
pixel refers to the same geographic location in every year, which is
required for accurate pixel-wise change detection.

**Stage 2 — Analysis**
Loads the aligned rasters and produces:
- Per-year area statistics for every land cover class
- Bar charts showing class distribution for each year
- Composite bar chart comparing all years side by side
- Change detection maps between consecutive years
- Transition matrices and heatmaps
- Multi-year trend lines with percentage labels

## Why the Pipeline Has Two Stages

Alignment and analysis solve different problems and fail in different ways:

- **Alignment** is I/O-heavy and geometric — it fixes coordinate systems
  and grids.
- **Analysis** is CPU-heavy and analytical — it computes statistics and
  change.

Keeping them separate means you can re-run the analysis as often as you
like (to tweak colors, labels, or comparisons) without re-doing the
slow alignment step every time.

## Requirements

- Python 3.9 or newer
- See `requirements.txt` for package versions

Install everything with:

```bash
pip install -r requirements.txt
```

## Setup

1. **Clone or download this repository** to a folder on your computer.

2. **Create a virtual environment** (recommended):

   ```bash
   python3 -m venv venv
   source venv/bin/activate        # macOS / Linux
   # or: venv\Scripts\activate     # Windows
   ```

3. **Install dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

4. **Prepare your data**:

   - Put your raw classified `.tif` files in `raw_rasters/`
   - Edit `classes.csv` to define your class codes, names, and colors
   - Edit `config.yaml` to set your target CRS and other options

## Usage

Run the two stages in order from the project folder:

```bash
# Step 1: reproject and align raw rasters
python run_alignment.py

# Step 2: compute statistics, change detection, and trends
python run_analysis.py
```

No Python code needs to be edited to use a different study area — all
project-specific settings live in `config.yaml` and `classes.csv`.

## Configuration

All settings are in `config.yaml`:

| Setting | Purpose | Example |
|---|---|---|
| `input_dir` | Folder with raw rasters | `raw_rasters` |
| `aligned_dir` | Where Stage 1 writes output | `aligned_rasters` |
| `output_dir` | Where Stage 2 writes output | `outputs` |
| `class_csv` | Class definitions file | `classes.csv` |
| `target_epsg` | Target coordinate system | `32630` (UTM Zone 30N) |
| `nodata` | Value representing NoData | `0` |
| `resampling` | Resampling method | `nearest` |

### Choosing the Right `target_epsg`

Pick the UTM zone that covers your study area. Some examples:

| Region | EPSG |
|---|---|
| Ghana | 32630 |
| Kenya | 32637 |
| Nigeria | 32631 |
| South Africa (west) | 32734 |
| Brazil (Amazon) | 32723 |

If you're unsure, search for "UTM zone [your country]" to find the right one.

### Why `nearest` Resampling?

Classified rasters hold categorical values (class codes like 1, 2, 3).
Averaging neighboring pixels could produce a value that doesn't
correspond to any real class. Nearest-neighbour resampling preserves
the original class labels.

## Class Definitions

`classes.csv` must have at least three columns:

```csv
code,name,color
1,Closed Savannah,#358221
2,Open Savannah,#A7D282
3,Grassland,#EECFA8
4,Farmland,#FFDB5C
5,Built-Up,#ED022A
6,Waterbody,#1A5BAB
7,Mining Area,#FFFFFF
8,Bareland,#ede9e4
```

- **code** — the integer value used in your raster files
- **name** — human-readable label for charts
- **color** — hex color for visualizations

## Output Structure

After running both stages, the `outputs/` folder contains:

```
outputs/
├── statistics.csv                  # Per-year class area table
├── yearly_graphs/
│   ├── bar_graph_2005.png          # One per year
│   ├── bar_graph_2015.png
│   ├── bar_graph_2025.png
│   └── all_years_composite.png     # All years in one figure
├── change_detection/
│   ├── change_map_2005_2015.tif    # Raster of encoded transitions
│   ├── change_stats_2005_2015.csv  # Per-transition statistics
│   ├── heatmap_2005_2015.png       # Transition matrix heatmap
│   ├── transition_area_*.csv       # Area matrices
│   └── transition_percent_*.csv    # Percentage matrices
└── trend_analysis/
    ├── trend_area.png              # Area trends with labels
    ├── trend_percentage.png        # Percentage trends with labels
    └── trend_data.csv              # Underlying trend numbers
```

## Spatial Logic

### Change Encoding

Change between two years is encoded as `from_class * 10 + to_class`.
For example:

- A pixel that stays Farmland (class 4) → encoded as `44`
- A pixel that changes from Farmland (4) to Built-Up (5) → encoded as `45`

This makes the change raster self-describing: each value tells you both
the source and destination class.

### Common Valid Mask

Stage 1 also produces `common_valid_mask.tif` — a binary raster marking
pixels that are valid (non-NoData) in **every** year. Stage 2 only
compares pixels within this mask, which prevents fake "changes" caused
by clouds, sensor gaps, or raster edges.

## Project Structure

```
landcover-change/
├── landcover/                      # The Python package
│   ├── __init__.py
│   ├── config.py                   # Loads config.yaml
│   ├── helpers.py                  # Shared utility functions
│   ├── stage1_alignment.py         # Reprojection and alignment
│   └── stage2_analysis.py          # Statistics, change, trends
│
├── raw_rasters/                    # Your input .tif files (gitignored)
├── aligned_rasters/                # Stage 1 output (gitignored)
├── outputs/                        # Stage 2 output (gitignored)
├── venv/                           # Virtual environment (gitignored)
│
├── config.yaml                     # All pipeline settings
├── classes.csv                     # Class definitions
├── requirements.txt                # Python dependencies
├── run_alignment.py                # Entry point for Stage 1
├── run_analysis.py                 # Entry point for Stage 2
├── .gitignore
└── README.md
```

## License

MIT