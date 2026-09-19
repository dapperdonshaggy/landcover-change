# USAGE

A practical guide to running the land cover change detection pipeline
on any study area.

---

## The Big Picture

```
1. Get the code         →  Clone or download the repo
2. Set up Python        →  Virtual environment + install packages
3. Prepare your data    →  Raw rasters + classes.csv + config.yaml
4. Run Stage 1          →  Reproject and align
5. Run Stage 2          →  Statistics, change detection, trends
6. View results         →  Open the outputs/ folder
```

No Python editing required — all settings live in `config.yaml`
and `classes.csv`.

---

## Step 1 — Get the Code

### Option A: Clone with Git (recommended)

```bash
cd ~/Desktop
git clone https://github.com/dapperdonshaggy/landcover-change.git
cd landcover-change
```

### Option B: Download as ZIP

1. Go to https://github.com/dapperdonshaggy/landcover-change
2. Click the green **Code** button → **Download ZIP**
3. Unzip it into a folder (e.g., `~/Desktop/landcover-change/`)
4. Open Terminal and navigate to it:

```bash
cd ~/Desktop/landcover-change
```

---

## Step 2 — Set Up Python

Do this once per computer.

### 2a. Create a virtual environment

```bash
python3 -m venv venv
```

This creates a `venv/` folder — a private Python environment for
this project only.

### 2b. Activate it

```bash
source venv/bin/activate        # macOS / Linux
# or: venv\Scripts\activate     # Windows
```

You'll see `(venv)` appear at the start of your Terminal prompt.
**Every time you open a new Terminal, you must run this again.**

### 2c. Install dependencies

```bash
pip install -r requirements.txt
```

Takes 1–3 minutes. Wait for `Successfully installed ...` at the end.

### 2d. Verify it worked

```bash
python -c "import numpy, pandas, rasterio, matplotlib, seaborn, yaml; print('All packages OK')"
```

Expected output: `All packages OK`

---

## Step 3 — Prepare Your Data

You need three things in place.

### 3a. Raw classified rasters

Put your `.tif` files into `raw_rasters/`:

```bash
cp /path/to/your/raster_files/*.tif raw_rasters/
```

**Requirements for your rasters:**

| Requirement | Why |
|---|---|
| **Classified** — each pixel is a class code (1, 2, 3...), not reflectance values | The pipeline detects change between *classes*, not raw values |
| **One file per year** — filenames must contain a 4-digit year | The pipeline extracts the year from the name |
| **Same class scheme across years** | If 1995 uses different class codes than 2005, results are meaningless |
| **GeoTIFF format** (`.tif` / `.tiff`) | What rasterio reads |

**Example filenames** (any format works as long as there is a 4-digit year):

- `Ghana_1995.tif`, `Ghana_2005.tif`, `Ghana_2015.tif`
- `LULC_2000.tif`, `LULC_2010.tif`, `LULC_2020.tif`
- `MyArea_1990.tif`, `MyArea_2020.tif`

### 3b. Class definitions — `classes.csv`

Edit `classes.csv` to match **your** classes. Format:

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

- **code** must match the pixel values in your rasters
- **name** is what appears on charts
- **color** is any hex color (search "hex color picker" online)

### 3c. Config — `config.yaml`

Open `config.yaml` and adjust:

```yaml
input_dir: raw_rasters
aligned_dir: aligned_rasters
output_dir: outputs
class_csv: classes.csv

target_epsg: 32630     # ← CHANGE THIS for your study area
nodata: 0
resampling: nearest

file_pattern: "*.tif"
year_pattern: "\\d{4}"
figure_dpi: 300
```

**The only setting you usually need to change is `target_epsg`.**

Find your UTM zone here:
https://mangomap.com/robertyoung/maps/69585/what-utm-zone-am-i-in-#

Enter your study area's central longitude and read off the EPSG code.

Common UTM zones:

| Region                | EPSG  |
|-----------------------|-------|
| Ghana                 | 32630 |
| Kenya                 | 32637 |
| Nigeria               | 32631 |
| South Africa (west)   | 32734 |
| Brazil (Amazon)       | 32723 |
| India                 | 32643 |

---

## Step 4 — Run Stage 1 (Alignment)

```bash
python run_alignment.py
```

**What it does:**

1. Finds all `.tif` files in `raw_rasters/`
2. Reprojects each to your `target_epsg`
3. Aligns them all to a common grid
4. Creates a common valid-pixel mask

**Output:** `aligned_rasters/` folder with:

- `<name>_reprojected.tif` — intermediate files
- `<name>_aligned.tif` — final aligned files
- `common_valid_mask.tif` — mask of pixels valid in all years

**Success indicator:** the last line should say

```
STAGE 1 COMPLETE — N aligned rasters saved
```

---

## Step 5 — Run Stage 2 (Analysis)

```bash
python run_analysis.py
```

**What it does:**

1. Loads all aligned rasters
2. Computes per-year class statistics
3. Creates yearly bar charts and a composite figure
4. Detects change between consecutive years
5. Builds transition matrices and heatmaps
6. Generates multi-year trend lines

**Output:** `outputs/` folder with subfolders for statistics,
graphs, change detection, and trends.

**Check the output** — the "Loaded years:" line should list your
years once each (no duplicates).

---

## Step 6 — View the Results

```bash
open outputs/
```

This opens Finder. You'll see:

| Folder / File         | What's Inside                           |
|-----------------------|-----------------------------------------|
| `statistics.csv`      | Table of class areas per year           |
| `yearly_graphs/`      | Bar charts (one per year + composite)   |
| `change_detection/`   | Change maps, transition matrices, heatmaps |
| `trend_analysis/`     | Multi-year trend lines and CSV          |

Open any `.png` file to see a graph. Open `.csv` files in Excel
or Numbers.

---

## Cheat Sheet

### First time setup on a new computer

```bash
cd ~/Desktop
git clone https://github.com/dapperdonshaggy/landcover-change.git
cd landcover-change

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp /path/to/your/*.tif raw_rasters/
# Edit classes.csv and config.yaml as needed
```

### Every time you run it

```bash
cd ~/Desktop/landcover-change
source venv/bin/activate

python run_alignment.py    # Stage 1
python run_analysis.py     # Stage 2

open outputs/              # View results
```

### Every time you change something

```bash
git add .
git commit -m "Describe your change"
git push
```

---

## Common Questions

### "What if I have different years than 1995/2005/2015/2025?"

Any years work. Just make sure filenames contain the year and each
year appears once.

Example: `CountryName_2001.tif`, `CountryName_2006.tif`,
`CountryName_2011.tif`

### "What if my rasters are already in the right CRS?"

Run Stage 1 anyway. It also handles alignment (making grids match),
which is required for change detection.

### "What if I only have 2 years?"

Fine — the pipeline works with 2 or more years. You'll get one
change detection pair instead of several.

### "What if I want to add another year later?"

Drop the new `.tif` in `raw_rasters/`, then re-run both stages.
It takes a couple of minutes.

### "Can I delete `raw_rasters/` after running?"

Yes — but keep a backup elsewhere. The repo's `.gitignore` means
Git never saw them, so they're not on GitHub.

### "Can I use this on Windows?"

Yes. Just:

- Use `venv\Scripts\activate` instead of `source venv/bin/activate`
- Replace `open` with `start` for opening folders

### "What if I get a `ModuleNotFoundError`?"

Your virtual environment isn't active. Run:

```bash
source venv/bin/activate
```

You should see `(venv)` in your prompt.

### "What if I see the wrong number of years?"

Check the `Loaded years:` line in Stage 2 output. If a year appears
twice, you have two files for the same year in `raw_rasters/`.
Remove one.

### "What if I get `No raster files found`?"

Your `.tif` files are not in `raw_rasters/`, or they have a different
extension. Check with:

```bash
ls raw_rasters/
```

---

## Worked Example — Kenya 2000 to 2020

Suppose you want to analyze land cover change in **Kenya** from
2000 to 2020.

```bash
# 1. Get the code
cd ~/Desktop
git clone https://github.com/dapperdonshaggy/landcover-change.git
cd landcover-change

# 2. Set up Python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Put your Kenya rasters in raw_rasters/
cp /path/to/Kenya_2000.tif raw_rasters/
cp /path/to/Kenya_2010.tif raw_rasters/
cp /path/to/Kenya_2020.tif raw_rasters/

# 4. Edit config.yaml
#    Change target_epsg to 32637 (Kenya UTM Zone 37N)

# 5. Edit classes.csv to match Kenya's classification scheme
#    (e.g., Forest, Shrubland, Cropland, Water, Built-Up...)

# 6. Run the pipeline
python run_alignment.py
python run_analysis.py

# 7. View results
open outputs/
```

**Done.** Same code, different country, zero Python edits.

---

## TL;DR

| If you want to...                  | Do this                                                                 |
|------------------------------------|-------------------------------------------------------------------------|
| Use it on a new study area         | Clone repo, put rasters in `raw_rasters/`, edit `config.yaml` and `classes.csv`, run both stages |
| Re-run analysis after editing      | `python run_analysis.py` (no need to re-align)                          |
| Add a new year                     | Drop file in `raw_rasters/`, run both stages                            |
| Change chart colors                | Edit `classes.csv`, run only `python run_analysis.py`                   |
| Change target CRS                  | Edit `config.yaml`, run both stages                                     |
| Save your changes                  | `git add . && git commit -m "..." && git push`                          |
| Share the project                  | Send the GitHub URL                                                     |


## Technical Notes

### Vectorization

The pipeline uses NumPy's vectorized operations wherever they matter:

- **NoData masking**: `np.isin()` masks every pixel not in the class
  list in a single pass, rather than looping pixel-by-pixel.
- **Common valid mask** (Stage 1): all rasters are stacked into a 3D
  array and reduced with `np.all(..., axis=0)` in one operation.
- **Class counting**: `np.bincount()` computes every class count in a
  single pass over the raster — no loop over classes.
- **Change encoding** (Stage 2): transitions are computed with
  `data1[valid] * 10 + data2[valid]` — a pure NumPy expression.
- **Transition statistics**: `np.bincount()` on the change matrix
  gives every (from, to) count in one pass, replacing the naive
  nested-loop approach.

Where loops remain (e.g. iterating over year pairs, or building CSV
rows), they exist for readability and don't affect performance at
typical dataset sizes.

### Why `np.bincount` Instead of Loops

`np.bincount` scans the raster once and increments a counter for each
value it encounters. A naive approach would scan the entire raster
once per class — O(n_classes × n_pixels) work instead of O(n_pixels).

For an 8-class, 5-million-pixel raster, that's the difference between
~5 million and ~40 million array operations.