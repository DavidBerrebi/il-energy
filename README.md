# il-energy — Israeli Energy Compliance Engine (SI 5282)

An automated engine that wraps EnergyPlus as a black-box simulation tool, extracts energy metrics, and computes residential/commercial energy ratings per the Israeli standard ת"י 5282.

---

## Requirements

- Python 3.9+
- EnergyPlus 25.2.0 installed at `/Applications/EnergyPlus-25-2-0/`
- Israeli EPW weather files (see [weather/README.md](weather/README.md))

```bash
pip install -e .
```

---

## Pipeline Overview

```
IDF file (any version)          EPW weather file
       │                               │
       ▼                               │
┌─────────────────────────────────┐    │
│  idf_parser.py                  │    │
│  • Auto-detects EP 8.x IDFs     │    │
│  • Runs idf_v89_converter.py    │    │
│    (DesignBuilder → EP 25.2)    │    │
│  • Injects Output:SQLite        │    │
└───────────────┬─────────────────┘    │
                │                      │
                ▼                      ▼
        ┌───────────────────────────────────┐
        │  runner.py  →  EnergyPlus 25.2    │
        │  subprocess: -a -x -r             │
        └─────────────────┬─────────────────┘
                          │
                          ▼
                    eplusout.sql
                          │
                          ▼
              ┌──────────────────────┐
              │  sql_parser.py       │
              │  metrics.py          │
              │  zone_aggregator.py  │
              └──────────┬───────────┘
                         │
              ┌──────────┴───────────┐
              │   SimulationOutput   │
              │  (kWh, m², zones)    │
              └──────────┬───────────┘
                         │
        ┌────────────────┴────────────────┐
        │                                 │
        ▼                                 ▼
  compare-residential              compare (commercial)
  (SI 5282 Part 1)                 (SI 5282 Part 2)
        │                                 │
        ▼                                 ▼
  box_generator.py              generator.py
  100 m² reference unit         Reference constructions
  4 orientations × EPref        from Table ג-1
        │                                 │
        └────────────┬────────────────────┘
                     │
                     ▼
             calculator.py
         IP = (EPref − EPdes) / EPref × 100
         Grade: A+ / A / B / C / D / E / F
```

---

## CLI Commands

### Run a single simulation
```bash
il-energy run \
  --idf  path/to/building.idf \
  --epw  path/to/weather.epw \
  --output-dir ./results
```
Outputs `results/simulation_output.json` with site energy, end-uses, zone data, and building area.

---

### Parse an existing SQL output (no re-simulation)
```bash
il-energy parse --sql path/to/eplusout.sql
```

---

### SI 5282 Part 1 — Residential Rating
```bash
il-energy compare-residential \
  --idf  models/fishman18.idf \
  --epw  "ClimateIsrael/ISR_TA_Tel.Aviv-Ben.Gurion.Intl.AP.401800_TMYx.2007-2021.epw" \
  --output-dir ./output/fishman_residential \
  --zone B \
  --floor-type middle
```

**Method:**
- Runs the proposed building simulation
- Runs the SI 5282 standard 100 m² reference box (10×10×3 m) for all 4 cardinal orientations
- `EPref = avg(HVAC_thermal_N + E + S + W) / 4 / COP(3.0) / 100 m²`
- `EPdes = (proposed_cooling + heating) / COP / conditioned_area`
- `IP = (EPref − EPdes) / EPref × 100%`

`--floor-type` options: `middle` (default), `top`, `ground`, `open`

Outputs `residential_rating.json`.

---

### SI 5282 Part 2 — Commercial Rating (approximate)
```bash
il-energy compare \
  --idf  models/building.idf \
  --epw  path/to/weather.epw \
  --output-dir ./output/comparison \
  --zone B
```

Replaces exterior opaque constructions with reference U-values from SI 5282 Table ג-1, runs both simulations, and produces an H-value comparison table and IP/grade.

Outputs `comparison_result.json`.

---

## Climate Zones

| Code | City | SI 5282 Standard Zone |
|------|------|-----------------------|
| A | Eilat | Zone D (extreme hot-arid) |
| B | Tel Aviv | Zone A (hot-humid) |
| C | Jerusalem | Zone C (temperate) |

---

## IDF Compatibility

The engine accepts **any IDF version**. DesignBuilder EP 8.9 IDFs are automatically converted to EP 25.2 format by `idf_v89_converter.py`, which handles:

| Change | Details |
|--------|---------|
| `WindowProperty:ShadingControl` | Converted to zone-based `WindowShadingControl` |
| `FenestrationSurface:Detailed` | Inline shading control field removed |
| `BuildingSurface:Detailed` | Blank `Space Name` field inserted (EP 9.x) |
| `InternalMass` | Blank `Space or SpaceList Name` field inserted |
| `RunPeriod` | `Begin Year` / `End Year` fields added; `UseWeatherFile` day fixed |
| `ShadowCalculation` | Method renamed; `Update Frequency Method` field inserted |
| `People` | `ZoneAveraged` → `EnclosureAveraged` |
| Version | Updated to `25.2` |

---

## Project Structure

```
src/il_energy/
├── cli.py                        # CLI entry point (click)
├── config.py                     # EnergyPlus path & defaults
├── models.py                     # Pydantic schemas
├── exceptions.py
├── simulation/
│   ├── runner.py                 # EnergyPlus subprocess wrapper
│   ├── idf_parser.py             # Output injection + v8.x auto-conversion
│   └── idf_v89_converter.py      # DesignBuilder EP 8.9 → EP 25.2 converter
├── postprocessing/
│   ├── metrics.py                # SQL → SimulationOutput
│   ├── normalizer.py             # J → kWh, per-m² normalization
│   └── zone_aggregator.py        # Zone grouping into flats
├── reference/
│   ├── generator.py              # SI 5282 reference building (commercial)
│   └── box_generator.py          # SI 5282 100 m² reference unit (residential)
└── rating/
    └── calculator.py             # IP computation, grade lookup

standards/si5282/
├── rating_thresholds.json        # Grade thresholds (A+ … F)
├── envelope_limits.yaml          # U-value limits by zone/grade
├── glazing_thresholds.json       # SHGC/U limits
└── ...                           # Wind, ventilation, frames data

models/                           # IDF files (gitignored)
weather/                          # EPW files (gitignored)
```

---

## Output Files

### `simulation_output.json`
```json
{
  "site_energy_kwh": 123456.0,
  "building_area": { "total_m2": 2800.0, "conditioned_m2": 2167.0 },
  "end_uses": {
    "cooling_kwh": 450000.0, "heating_kwh": 1200.0,
    "interior_lighting_kwh": 85000.0, "interior_equipment_kwh": 120000.0
  },
  "zones": [...],
  "flats": [...]
}
```

### `residential_rating.json`
```json
{
  "standard": "SI 5282 Part 1",
  "climate_zone": "B",
  "ep_des_kwh_m2": 78.22,
  "ep_ref_kwh_m2": 39.84,
  "ip_percent": -96.4,
  "grade": { "grade": "F", "name_en": "Below Base", "name_he": "לא עומד", "score": -1 }
}
```

### `comparison_result.json`
Full H-value table comparing proposed vs. reference end-uses per m².

---

## Running Tests

```bash
pytest
pytest -m integration   # requires EnergyPlus installed
```
