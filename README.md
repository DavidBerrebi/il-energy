# il-energy — Israeli Energy Compliance Engine (SI 5282)

An automated engine that wraps EnergyPlus as a black-box simulation tool, extracts energy metrics, and computes residential energy ratings per the Israeli standard ת"י 5282 Part 1 (2024 amendment).

---

## Prerequisites & Setup

### 1. Install EnergyPlus 25.2.0

EnergyPlus is the simulation engine that powers this tool. It is a standalone binary, not a Python package.

**Download:** <https://github.com/NREL/EnergyPlus/releases/tag/v25.2.0>

| Platform | Installer | Default path after install |
|----------|-----------|---------------------------|
| macOS    | `.dmg`    | `/Applications/EnergyPlus-25-2-0/` |
| Linux    | `.sh`     | `/usr/local/EnergyPlus-25-2-0/` |
| Windows  | `.exe`    | `C:\EnergyPlusV25-2-0\` |

If you install to a custom location, set the `ENERGYPLUS_DIR` environment variable (see step 3).

> **Note on IDF versions:** Input models are typically exported from DesignBuilder in EnergyPlus 8.9 format. The engine auto-converts them to EP 25.2 before running — you do **not** need EnergyPlus 8.9 installed.

### 2. Install Python dependencies

```bash
# Python 3.9+ required
pip install -e .

# Optional extras
pip install -e ".[gui]"   # desktop GUI (Tkinter + PDF viewer)
pip install -e ".[web]"   # web interface (FastAPI)
pip install -e ".[dev]"   # dev tools (pytest, ruff)
```

### 3. Configure EnergyPlus path (if needed)

If EnergyPlus is installed at the default path for your platform, nothing extra is needed — the engine finds it automatically.

For a custom install location, copy the example env file and set your path:

```bash
cp .env.example .env
# Then edit .env and set:
# ENERGYPLUS_DIR=/your/custom/path/to/EnergyPlus-25-2-0
```

Or export directly in your shell:

```bash
export ENERGYPLUS_DIR=/path/to/EnergyPlus-25-2-0
# ENERGYPLUS_PATH is also accepted as an alias
```

### 4. Obtain EPW weather files

Israeli EPW files are not included in the repository. Obtain them separately and note their paths — you will pass them to the CLI with `--epw`.

---

## Quick Start — Residential Rating

```bash
il-energy compare-residential \
  --idf   "path/to/building.idf" \
  --epw   "path/to/ISR_TA_Tel.Aviv-Sde.Dov_.AP_.401762_TMYx.2007-2021_WindStandardized_Modified IMS.epw" \
  --output-dir ./output/my_project \
  --zone B
```

This single command:
1. Auto-converts EP 8.x / 9.x IDFs to EP 25.2 format
2. Applies SI 5282 reference operating conditions (thermostat schedules, occupancy, lighting, ventilation)
3. Runs the proposed building simulation (EP 25.2)
4. Looks up calibrated EPref values from the tabulated Zone B table (≈ 1 second)
   — or runs reference-box simulations for zones without a table (≈ 12–16 EP runs)
5. Detects penthouse / setback units via roof-area ratio
6. Computes per-unit IP and grade (A+ … F) for every apartment
7. Generates `residential_report.md`, `units.csv`, and `windows.csv`

**Output directory will contain:**

| File | Contents |
|------|----------|
| `residential_rating.json` | Full results: building grade, per-unit ratings, EPref/EPdes |
| `residential_report.md` | Professional Markdown report |
| `units.csv` | Per-unit table matching EVERGREEN `output.csv` format |
| `windows.csv` | Per-surface window analysis (U, SHGC, WWR, shading) |
| `proposed/eplusout.sql` | Raw EnergyPlus SQL output |

---

## CLI Commands

### `compare-residential` — SI 5282 Part 1 Residential Rating

```bash
il-energy compare-residential \
  --idf        path/to/building.idf \
  --epw        path/to/weather.epw \
  --output-dir ./output/project \
  --zone       B                    # A / B / C  (auto-detected from EPW if omitted)
  --simulate-epref                  # optional: force reference-box simulation instead of table
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--idf` | required | Proposed building IDF (EP 8.x, 9.x, or 25.x — auto-converted) |
| `--epw` | required | EnergyPlus weather file (.epw) |
| `--output-dir` | required | Directory for all outputs |
| `--zone` | auto | SI 5282 climate zone: A, B, or C. Auto-detected from EPW filename if omitted |
| `--simulate-epref` | off | Force reference-box simulation (12–16 EP runs) instead of tabulated EPref |

**EPref method — tabulated vs simulated:**

By default, Zone B uses pre-calibrated tabulated EPref values (from `standards/si5282/ep_ref_values.json`). These were reverse-engineered from EVERGREEN v3.0.4 results and give the best grade match against expert output. Pass `--simulate-epref` to instead compute EPref from live EP 25.2 reference-box simulations — useful for new zones or research.

| EPref source | Zone B matches (Nili 24 units) | Speed |
|---|---|---|
| Tabulated (default) | 19/24 | ~30 sec (1 EP run) |
| Simulated box | 18/24 | ~3–5 min (12–16 EP runs) |

**Method:**

```
EPdes = Σ(zone cooling + heating) / COP(3.0) / conditioned_area_m²   [kWh/m²/yr electrical]
EPref = tabulated[floor_type][area_category]                           [Zone B]
      = avg(HVAC_thermal × 4 orientations) / COP / 100 m²             [Zones A, C]
IP    = (EPref − EPdes) / EPref × 100 %
```

Floor types assigned automatically:
- Floor 0 (lowest number) → `ground`
- Highest floor number → `top`
- All others → `middle`
- Any unit whose exterior horizontal roof area ≥ 50% of floor area → promoted to `top`

Small-unit threshold (≤ 50 m²): uses higher `small_le50m2` EPref value (Zone B only).

---

### `run` — Raw EnergyPlus Simulation

```bash
il-energy run \
  --idf        path/to/building.idf \
  --epw        path/to/weather.epw \
  --output-dir ./results
```

Runs EnergyPlus and writes `simulation_output.json` with site energy, end-uses, zone data, and building area. No rating calculation.

---

### `parse` — Extract Metrics from Existing SQL

```bash
il-energy parse --sql path/to/eplusout.sql
il-energy parse --sql path/to/eplusout.sql -o output.json
```

Parses an existing `eplusout.sql` without re-running EnergyPlus. Useful for re-processing results.

---

### `compare` — SI 5282 Commercial Rating (approximate)

```bash
il-energy compare \
  --idf        path/to/building.idf \
  --epw        path/to/weather.epw \
  --output-dir ./output/comparison \
  --zone B
```

Replaces exterior opaque constructions with SI 5282 Table ג-1 reference U-values, runs both simulations, and produces an H-value (EUI) comparison table and IP/grade. Outputs `comparison_result.json`.

---

## Climate Zones

Auto-detected from EPW filename when `--zone` is omitted.

| Zone | City | EPW WMO | EPref source |
|------|------|---------|--------------|
| B | Tel Aviv / Holon / Ashkelon (coastal) | 401762 | Tabulated (calibrated) |
| A | Eilat, Beer Sheva (hot-arid) | 401990 | Reference-box simulation |
| C | Jerusalem, highland | 401830 | Reference-box simulation |

---

## IDF Compatibility

The engine accepts **any IDF version**. Conversion is automatic:

| Source version | Converter | Key changes |
|---|---|---|
| EP 8.x (DesignBuilder 5.x) | `idf_v89_converter.py` | WindowShadingControl, Space Name fields, RunPeriod, ShadowCalculation, ZoneAveraged→EnclosureAveraged, version bump |
| EP 9.x (DesignBuilder 6.x) | `idf_v9x_converter.py` (inside `idf_v89_converter.py`) | Space Name insertion, ZoneAveraged fix, version bump |
| EP 25.x | — | Used as-is |

---

## EPref Tabulated Values (Zone B)

Stored in `standards/si5282/ep_ref_values.json`. Calibrated against EVERGREEN v3.0.4 results on the NILI Holon project (Zone B).

| Floor type | Area | EPref [kWh/m²/yr electrical] |
|---|---|---|
| Ground | any | 28.94 |
| Middle | > 50 m² | 38.04 |
| Middle | ≤ 50 m² | 44.89 |
| Top | any | 41.34 |

> **Note:** These values are calibrated for EP 25.2. The expert software (EVERGREEN) runs EP 9.4 reference boxes and produces slightly different values (≈4% lower for middle/top). This is an EP-version gap in the reference building thermal model — ground floor reference is nearly identical across versions.

To add Zone A or C tabulated values: set the zone entry in `ep_ref_values.json` to a dict with the same structure as Zone B. Until then, those zones use live reference-box simulation.

---

## Zone Naming Support

The aggregator recognises several residential zone naming conventions:

| Pattern | Example | Flat ID | Floor |
|---|---|---|---|
| Nili-style (digit-first) | `00X1:LIVING` | `00X1` | 0 |
| Letter-first | `FF01:LIVING` | `FF01` | — |
| FLAT/APT/UNIT prefix | `FLAT_3_BEDROOM` | `FLAT_3` | — |

CORE/corridor zones are excluded from flat aggregation automatically.

---

## Project Structure

```
src/il_energy/
├── cli.py                         CLI entry point (click)
├── config.py                      EnergyPlus path & zone detection
├── models.py                      Pydantic schemas
├── exceptions.py
├── simulation/
│   ├── runner.py                  EnergyPlus subprocess wrapper
│   ├── idf_parser.py              Output injection + version auto-conversion
│   ├── idf_v89_converter.py       EP 8.x / 9.x → EP 25.2 converter
│   ├── sql_parser.py              eplusout.sql → SimulationOutput
│   └── si5282_preprocessor.py     SI 5282 reference operating conditions
├── postprocessing/
│   ├── metrics.py                 SQL → SimulationOutput orchestrator
│   ├── normalizer.py              J → kWh, per-m² normalization
│   └── zone_aggregator.py         Zone grouping into flats + floor-type detection
├── reference/
│   ├── generator.py               SI 5282 reference building (commercial)
│   └── box_generator.py           SI 5282 100 m² reference unit (residential)
├── rating/
│   └── calculator.py              IP computation, per-unit grades, grade lookup
├── analysis/
│   └── windows.py                 Window U/SHGC/WWR extraction
└── report/
    └── generator.py               Markdown report + CSV output

standards/si5282/
├── ep_ref_values.json             Tabulated EPref by zone/floor type/area
├── rating_thresholds.json         Grade thresholds (A+ … F)
├── envelope_limits.yaml           U-value limits by zone/grade
└── glazing_thresholds.json        SHGC/U limits
```

---

## Output Files

### `residential_rating.json`
```json
{
  "standard": "SI 5282 Part 1",
  "climate_zone": "B",
  "conditioned_area_m2": 2109.4,
  "ep_des_kwh_m2": 29.64,
  "ep_ref_kwh_m2": 38.04,
  "ip_percent": 22.1,
  "grade": { "grade": "B", "name_en": "Gold", "name_he": "זהב", "score": 3 },
  "unit_ratings": [
    {
      "flat_id": "01X2", "floor_number": 1, "floor_type": "middle",
      "area_m2": 48.8, "ep_des_kwh_m2": 29.18, "ep_ref_kwh_m2": 44.89,
      "ip_percent": 35.0, "grade": { "grade": "A", ... }
    },
    ...
  ]
}
```

### `units.csv`
Per-unit table in EVERGREEN-compatible format:
```
Multiplier, Grade, Rating (G), Floor Area {m2}, Orientation, Flat or Zone, Floor
```

### `windows.csv`
Per-surface window data:
```
Floor, Unit, Orientation, Unit Area, Surface, Construction, Net Area, Um, SHGC, VT, Shading, Window Orientation, WWR
```

---

## Running Tests

```bash
pytest
pytest -m integration   # requires EnergyPlus installed
```

---

## Validated Projects

| Project | Units | Our grade | Expert grade | Matches |
|---|---|---|---|---|
| NILI Holon (Zone B) | 24 | B | B ✓ | 19/24 (79%) |
| Ashkelon AB (Zone B) | 51 | A | B | 44/51 (86%) |
| Ashkelon CD (Zone B) | — | — | — | — |

> The remaining grade mismatches are due to an EnergyPlus 9.4→25.2 thermal model change affecting middle/top reference-box HVAC loads (~7% higher in EP 25.2). Ground floor is nearly identical across versions.
