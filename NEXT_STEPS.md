# Nili 10 (Holon) — Grade Accuracy: Experiment Summary & Next Steps

**Date:** 23 March 2026
**Status:** Building grade B achieved ✓ — per-unit grade accuracy needs improvement

---

## 1. What We Achieved

| Metric | Our Engine | Expert EVERGREEN | Delta |
|--------|-----------|-----------------|-------|
| EPdes (building) | 29.64 kWh/m²/yr | 28.17 kWh/m²/yr | +5.2% |
| EPref (building) | 39.16 kWh/m²/yr | 39.84 kWh/m²/yr | −1.7% |
| IP | +24.3% | +29.3% | −5 pp |
| **Building Grade** | **B (Gold/זהב)** | **B (Gold/זהב)** | **✓ Match** |
| Per-unit grade match | 13 / 24 units | — | 54% |

---

## 2. Root Causes Fixed

### Fix A — SI 5282 Reference Conditions Preprocessor
**Problem:** EVERGREEN pre-processes the design IDF before simulation, replacing design-specific
schedules with SI 5282 standard reference schedules. Without this, EPdes was 74.7 kWh/m²/yr.

**Solution:** `src/il_energy/simulation/si5282_preprocessor.py` — applied before proposed simulation.
Changes made to IDF:
1. Lighting schedule → `_EPrefResidentialGenLighting`; radiant fraction 0.72 → 0.28
2. Computing equipment schedule → `_EPrefResidentialComputer`; watts 10 → 9 W/m²
3. General equipment schedule → `_EPrefResidentialEquipment`; watts 3 → 1 W/m²
4. Shading schedule → `_EPrefResidentialShading A-B`
5. Infiltration schedule → `_EPrefResidentialInfiltration`
6. Added ZoneVentilation:DesignFlowRate (2 ACH natural, seasonal, per residential zone)

**Impact:** EPdes dropped from 74.7 → 56.1 kWh/m²/yr

### Fix B — EP 25.2 Latent Cooling Gap
**Problem:** EnergyPlus 25.2 computes ~167,070 kWh of latent cooling from dehumidifying 1 ACH
of humid Tel Aviv coastal air, inflating total HVAC to 354,669 kWh. EP 9.4 (used by EVERGREEN)
with `Dehumidification Control Type = None` produces near-zero latent (total ≈ sensible only).

**Solution:** Extract `Zone Ideal Loads Supply Air Sensible Cooling Rate` instead of `Total Cooling Rate`
from the SQL output (Strategy 2 in `sql_parser.py`). Derive building EPdes from zone sensible sums
instead of `end_uses.cooling_kwh`.

Files changed:
- `src/il_energy/simulation/sql_parser.py` — Strategy 2 uses `Sensible%Rate` pattern
- `src/il_energy/cli.py` — EPdes computed from zone sensible sums

**Impact:** EPdes dropped from 56.1 → 29.64 kWh/m²/yr (matches expert 28.17 within 5%)

---

## 3. Per-Unit Grade Comparison

The single-EPref approach (39.16 kWh/m²/yr for all units) causes 11 mismatches.
The expert uses different EPref per floor type and unit size.

| Unit | Floor | Type | Area m² | Our EPdes | Our Grade | Expert Grade | Status |
|------|-------|------|---------|-----------|-----------|-------------|--------|
| 00X1 | 0 | ground | 108.7 | 23.2 | A+ | A | DIFF (over-rate) |
| 00X2 | 0 | ground | 111.8 | 24.1 | A | B | DIFF (over-rate) |
| 01X1 | 1 | middle | 111.9 | 29.0 | B | B | ✓ |
| 01X2 | 1 | middle | 48.8 | 29.2 | B | A | DIFF (under-rate) |
| 01X3 | 1 | middle | 89.7 | 28.8 | B | B | ✓ |
| 01X4 | 1 | middle | 90.5 | 29.4 | B | B | ✓ |
| 02X1 | 2 | middle | 89.6 | 29.4 | B | B | ✓ |
| 02X2 | 2 | middle | 48.8 | 30.3 | B | A | DIFF (under-rate) |
| 02X3 | 2 | middle | 106.8 | 30.9 | B | C | DIFF (over-rate) |
| 02X4 | 2 | middle | 90.9 | 30.1 | B | B | ✓ |
| 03X1 | 3 | middle | 89.6 | 29.0 | B | B | ✓ |
| 03X2 | 3 | middle | 48.8 | 30.4 | B | A | DIFF (under-rate) |
| 03X3 | 3 | middle | 106.8 | 31.1 | B | C | DIFF (over-rate) |
| 03X4 | 3 | middle | 90.9 | 30.2 | B | B | ✓ |
| 04X1 | 4 | middle | 111.9 | 30.9 | B | B | ✓ |
| 04X2 | 4 | middle | 48.8 | 30.5 | B | A | DIFF (under-rate) |
| 04X3 | 4 | middle | 90.5 | 30.2 | B | B | ✓ |
| 04X4 | 4 | middle | 89.7 | 29.1 | B | B | ✓ |
| 05X1 | 5 | middle | 111.9 | 31.0 | B | C | DIFF (over-rate) |
| 05X2 | 5 | middle | 48.8 | 30.7 | B | A | DIFF (under-rate) |
| 05X3 | 5 | middle | 90.5 | 30.7 | B | B | ✓ |
| 05X4 | 5 | middle | 89.7 | 29.7 | B | B | ✓ |
| 06X1 | 6 | top | 81.4 | 33.2 | C | B | DIFF (under-rate) |
| 06X2 | 6 | top | 112.6 | 33.0 | C | C | ✓ |

**Summary:** 13/24 exact match. All 24 are within one grade of expert.

**Pattern analysis:**
- Ground units (00X1, 00X2): we over-rate → our EPref (39.16) is too high for ground floor; expert EPref ~28.94 kWh/m²/yr
- Small 48m² middle units (X2 series): we under-rate → expert EPref ~44–45 kWh/m²/yr for small units (smaller box = more exposure)
- Top-floor unit 06X1 (81m²): we under-rate → expert EPref ~41.34 kWh/m²/yr for top floor

---

## 4. Next Steps (Priority Order)

### Step 1 — Per-Floor-Type EPref  [HIGH PRIORITY]
**Expected impact: 5–8 more unit matches**

The expert uses a separate reference box simulation per floor type (ground / middle / top).
Each floor type has different exposure conditions → different EPref.

**Expert EPref by floor type (observed from expert output):**
- ground: ~28.94 kWh/m²/yr (lower — ground has earth contact, less exposure)
- middle: ~38–45 kWh/m²/yr (depends on unit area; small 48m² units get ~44.89)
- top: ~41.34 kWh/m²/yr (higher — roof exposure)

**Implementation plan:**
- `cli.py`: loop 3 floor types × 4 orientations = 12 reference box simulations instead of 4
- `box_generator.generate_reference_box_idf()` already accepts `floor_type` parameter — no change needed
- `calculator.compute_unit_ratings()` already accepts `ep_ref_by_floor_type: Dict[str, float]` — no change needed
- Only `cli.py` needs updating (~40 lines)

**Files to change:** `src/il_energy/cli.py` (lines ~279–321)

**Verification:** After fix, expect:
- ground units: EPref ~28–30 → grades A/B (currently A+/A because EPref too high)
- top unit 06X1: EPref ~41 → grade B (currently C)
- small 48m² units: EPref ~44–45 → grades A (currently B)

---

### Step 2 — Surface-Based Floor Type Override  [MEDIUM PRIORITY]
**Expected impact: Catch edge cases like unit 05X3 (has roof, on non-top floor)**

Some units have roof surfaces but aren't on the top floor (penthouses, setbacks).
Current auto-detection uses floor number only.

**Implementation plan:**
- Add `override_floor_types_from_surfaces()` to `src/il_energy/postprocessing/zone_aggregator.py`
- Logic: if zone has an exterior opaque surface with tilt < 10° (horizontal roof) → classify as `top`
- If zone has exterior opaque surface with tilt > 170° (downward floor) → classify as `open`
- Call after `aggregate_zones_to_flats()` in `cli.py`
- Verify `EnvelopeSurface` has `zone` field (it does — from `sql_parser.parse_opaque_surfaces()`)

---

### Step 3 — People/Occupancy Heat Gain  [LOW PRIORITY — investigate first]
**Status: unconfirmed gap**

Expert CSV shows `People Sensible Heat Addition` = 1,481 kWh per LIVING zone, suggesting
EVERGREEN also injects `_EPrefResidentialOccupancy` schedule and a People object.
Our preprocessor does NOT add People objects.

**Action:** Check if the Nili IDF already has People objects and whether adding EPref occupancy
would affect EPdes significantly. If EPdes rises by >5%, this needs implementing.

---

### Step 4 — Report H (Prescriptive U-value Check)  [SEPARATE SUBSYSTEM]
**Status: deferred — high complexity**

SI 5282 requires buildings to also pass a prescriptive envelope check (Report H):
- Compute Σ(U × A) for each unit across all wall/roof/window surfaces
- Compare against required H values from SI 5282 Table ג-2 (by climate zone)
- Requires surface-level U-values (available in `envelope_opaque` via `sql_parser`)

**Scope:** New module `src/il_energy/rating/prescriptive_check.py`. Deferred to future work.

---

### Step 5 — Semi-Exterior Windows (Balcony Walls)  [LOW PRIORITY]
Expert `windows.csv` has 916 rows; ours has 479.
The missing ~437 are likely balcony/semi-exterior walls treated as windows by EVERGREEN.
Investigate whether these affect energy simulation or only the report.

---

## 5. File Locations

| File / Output | Path |
|--------------|------|
| Final working output | `output/nili_sensible_fix/` |
| Building report | `output/nili_sensible_fix/residential_report.md` |
| Per-unit CSV | `output/nili_sensible_fix/units.csv` |
| Rating JSON | `output/nili_sensible_fix/residential_rating.json` |
| Expert results | `/Users/davidberrebi/Desktop/EnergyGreen/Nili/results/full_68bff30bdaf90996eed0c820/csv/` |
| Preprocessor | `src/il_energy/simulation/si5282_preprocessor.py` |
| SQL parser (sensible fix) | `src/il_energy/simulation/sql_parser.py` |
| CLI (EPdes from zones) | `src/il_energy/cli.py` |
| IDF converter (9.x→25.2) | `src/il_energy/simulation/idf_v89_converter.py` |
| Experiment memory | `.claude/projects/.../memory/project_nili_experiment.md` |
| Original detailed plan | `.claude/plans/jazzy-crunching-hearth.md` |

---

## 6. Quick Re-run Command

```bash
il-energy compare-residential \
  --idf "/Users/davidberrebi/Desktop/EnergyGreen/Nili/NILI 1007.idf" \
  --epw "/Users/davidberrebi/Desktop/EnergyGreen/ClimateIsrael/ISR_TA_Tel.Aviv-Sde.Dov_.AP_.401762_TMYx.2007-2021_WindStandardized_Modified IMS.epw" \
  --output-dir output/nili_sensible_fix \
  --zone B
```

Run tests after any code change:
```bash
cd /Users/davidberrebi/Desktop/EnergyGreen/ClaudeCodeProj && pytest tests/ -v
```
