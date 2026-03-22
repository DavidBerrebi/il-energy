# Energy Analysis Guide — What to Look For and How to Read Results

This guide explains which metrics matter for SI 5282 compliance, what the output numbers mean, and how to diagnose a building's energy performance from simulation results.

---

## 1. The Key Question: IP and Grade

The entire analysis reduces to one number — the **Improvement Percentage (IP)**:

```
IP = (EPref − EPdes) / EPref × 100%
```

| IP Range | Grade | Hebrew | Meaning |
|----------|-------|--------|---------|
| ≥ 40% | A+ | יהלום | Diamond — excellent |
| ≥ 30% | A | פלטינה | Platinum |
| ≥ 20% | B | זהב | Gold |
| ≥ 10% | C | כסף | Silver |
| ≥ 0% | D | ארד | Bronze — meets base |
| ≥ −10% | E | דרגת בסיס | Base grade |
| < −10% | F | לא עומד | Below base — fails |

A **positive IP** means the proposed building uses less energy than the reference → better than standard.
A **negative IP** means it uses more → worse than standard.

---

## 2. Residential Method (SI 5282 Part 1)

### Reference unit
The reference is a **standardized 100 m² box** (10 × 10 × 3 m), not the proposed building's geometry. It is simulated 4 times facing each cardinal direction and averaged.

```
EPref = average HVAC thermal (N + E + S + W) / 4   [kWh/yr]
      ÷ COP (3.0)
      ÷ 100 m²
      = [kWh/m²/yr electrical]
```

### Proposed building
```
EPdes = (annual cooling kWh + annual heating kWh)
      ÷ COP (3.0)
      ÷ conditioned floor area (m²)
      = [kWh/m²/yr electrical]
```

### What to check in `residential_rating.json`

```json
{
  "ep_des_kwh_m2": 78.22,           ← proposed energy intensity
  "ep_ref_kwh_m2": 39.84,           ← reference box energy intensity
  "ip_percent": -96.4,              ← negative = worse than reference
  "grade": { "grade": "F" },
  "ref_box_hvac_by_orientation": {
    "S": 11411.1,                   ← South orientation HVAC (kWh/yr)
    "W": 12313.9,
    "N": 11972.2,
    "E": 12108.3
  }
}
```

**Orientation spread** (W vs N vs S vs E) tells you how sensitive the reference box is to solar orientation. A large spread means solar gains dominate over conduction — important for window sizing decisions.

---

## 3. What Drives High EPdes — Diagnostic Checklist

Run `il-energy run` on the proposed building and open `simulation_output.json`. Look at end-uses in order of magnitude:

### 3.1 Cooling dominates
In Israeli climate (especially Zone B / Tel Aviv), **cooling is almost always the dominant end-use**. If cooling >> heating, the building has a solar gain problem.

Key things to check:
- **Window area (m²)** — large glazing areas in hot climates drive cooling
- **SHGC** — Solar Heat Gain Coefficient. Values > 0.4 in Zone B are problematic without external shading
- **Glazing orientation** — west and east facing windows are the worst for summer cooling
- **External shading** — SI 5282 requires external shutters for all windows > 0.3 m²

### 3.2 Heating significant in Zone C (Jerusalem)
If heating > 10% of HVAC total in Zone C, check:
- Insulation (wall U-value, roof U-value)
- Window U-value (double glazing required for cold nights)
- Air infiltration (airtightness)

### 3.3 Lighting / Equipment high
These appear in the H-value table for commercial comparisons. For residential (Part 1), only HVAC is used in the IP calculation — lighting and equipment do not affect the residential grade.

---

## 4. Reading the H-Value Table (Commercial, `comparison_result.json`)

```
H-VALUES (kWh/m²/yr):
End-use               Proposed    Reference        Delta
----------------------------------------------------------
Cooling                  207.77       166.56       -41.21   ← proposed uses MORE
Heating                    0.31         0.13        -0.18
HVAC Total               208.08       166.69       -41.39
Interior Lighting         22.14        22.14         0.00   ← same (not replaced)
Interior Equipment        32.16        32.16         0.00
Total Site Energy        262.38       220.99       -41.39
```

- **Negative delta** = proposed uses more than reference → bad
- **Zero delta** on lighting/equipment = correct (reference keeps proposed schedules/loads)
- The reference building has the same geometry but **standard U-values** on the envelope

---

## 5. Reference U-Values Used (SI 5282 Table ג-1)

These are the reference envelope values applied in the commercial comparison:

| Element | Zone A (Eilat) | Zone B (Tel Aviv) | Zone C (Jerusalem) |
|---------|----------------|--------------------|--------------------|
| Exterior wall | 0.943 W/m²K | 1.250 W/m²K | 1.031 W/m²K |
| Flat roof | 0.595 W/m²K | 0.595 W/m²K | 0.595 W/m²K |
| Ground floor | 1.176 W/m²K | 1.176 W/m²K | 1.176 W/m²K |
| Semi-exposed floor | 0.826 W/m²K | 1.190 W/m²K | 0.826 W/m²K |

If the proposed building has **lower U-values** than these references, the reference will use more energy than proposed → positive delta → IP goes up → better grade.

---

## 6. Reference Box Orientations — What to Look For

The 4-orientation box result tells you the **solar sensitivity** of the reference unit:

```
[S] 114.1 kWh/m²   ← south-facing: direct winter sun, moderate summer
[W] 123.1 kWh/m²   ← west-facing: highest afternoon summer loads
[N] 119.7 kWh/m²   ← north-facing: least direct sun
[E] 121.1 kWh/m²   ← east-facing: morning summer loads
```

The EPref uses the **average** of all four, which represents a "typical" unit without orientation bias. In Zone B, all orientations are close because cooling dominates year-round.

---

## 7. Glazing Sensitivity Analysis

To test the impact of window properties, use the `idf_v89_converter.py` pipeline and swap constructions manually (as done in the fishman analysis). Key findings for Zone B:

| Glazing Type | U (W/m²K) | SHGC | HVAC (kWh/m²) | IP | Grade |
|---|---|---|---|---|---|
| _4mm single | 5.87 | 0.847 | 234.7 | −96.4% | F |
| _4-6-4 double | 3.146 | 0.740 | 233.1 | −95.1% | F |

**Lesson**: In Tel Aviv's climate, changing from single to double glazing gives < 1% improvement. The dominant factor is **SHGC** (solar transmission), not U-value. To improve grade, use:
- Low-e double glazing: SHGC ≤ 0.35, U ≤ 1.8 W/m²K
- External shading (reduces effective SHGC to ~0.15–0.25)

---

## 8. Common Output Paths

After running any command, results are written to `--output-dir`:

| File | Contents |
|------|----------|
| `simulation_output.json` | Single simulation: energy, area, zones, flats |
| `residential_rating.json` | SI 5282 Part 1: EPdes, EPref, IP, grade |
| `comparison_result.json` | SI 5282 Part 2: H-table, IP, grade |
| `proposed/eplusout.sql` | Raw EnergyPlus database (proposed) |
| `reference/eplusout.sql` | Raw EnergyPlus database (reference) |
| `refbox_S.idf` … `refbox_E.idf` | Generated reference box IDFs (residential) |
| `reference.idf` | Generated reference building IDF (commercial) |

---

## 9. Fishman Building — Summary of Findings

As of March 2026, the fishman18 building (Tel Aviv, Zone B, residential):

| Item | Value |
|------|-------|
| Conditioned area | 2,167 m² |
| Number of windows | 152 |
| Total glazing area | ~538 m² |
| Current window glazing | `_4mm` single (U=5.87, SHGC=0.847) |
| HVAC thermal load | 234.7 kWh/m²/yr |
| EPdes | 78.22 kWh/m²/yr |
| EPref (reference box, Zone B) | 39.84 kWh/m²/yr |
| IP | −96.4% |
| Grade | **F — לא עומד** |

**Root cause**: The very high SHGC (0.847) across 538 m² of glazing in a hot climate generates enormous solar cooling loads. Switching to double glazing (`_4-6-4`, SHGC=0.740) yields only −95.1% IP — still F. The building needs low-SHGC glazing or external shading to improve meaningfully.
