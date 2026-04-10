"""Centralized constants for the il-energy pipeline.

All magic numbers, conversion factors, and SI 5282 standard values
are defined here to avoid duplication and improve readability.
"""

# ── Energy unit conversions ──────────────────────────────────────────────────

GJ_TO_KWH = 277.778
"""1 GJ = 277.778 kWh."""

J_TO_KWH = 1.0 / 3_600_000
"""1 J = 1/3,600,000 kWh."""

HOURS_PER_YEAR = 8760
"""Hours in a standard non-leap year."""

W_TO_KWH_PER_YEAR = HOURS_PER_YEAR / 1000.0
"""Convert average watts to kWh/year: avg_W * 8.76."""

# ── SI 5282 Part 1 — Rating ─────────────────────────────────────────────────

DEFAULT_COP = 3.0
"""Default HVAC Coefficient of Performance (Israeli heat pump standard)."""

REFERENCE_BOX_AREA_M2 = 100.0
"""Standard reference unit floor area per SI 5282 Appendix ג (m²)."""

SMALL_UNIT_THRESHOLD_M2 = 50.0
"""Units at or below this area get a higher EPref multiplier (m²)."""

SMALL_UNIT_FACTOR = 44.89 / 38.04
"""EPref multiplier for middle-floor units ≤ 50 m² (≈ 1.18).
From SI 5282 Part 1, 2024, Annex ג tabulated values."""

# ── SI 5282 Part 1 — Reference window (Table ג-1) ───────────────────────────

REF_WINDOW_U_W_M2K = 4.0
"""Reference window U-factor (W/m²K), same for all climate zones."""

REF_WINDOW_SHGC = 0.63
"""Reference window Solar Heat Gain Coefficient."""

# ── Cost projection ──────────────────────────────────────────────────────────

ELECTRICITY_RATE_NIS_PER_KWH = 0.62
"""Residential electricity tariff approximation (NIS/kWh)."""

COST_PROJECTION_YEARS = 5
"""Number of years for electricity cost projection (Evergreen convention)."""

# ── Envelope — H-indicator ───────────────────────────────────────────────────

DEFAULT_FRAME_CONDUCTANCE_W_M2K = 5.8
"""Fallback frame conductance (W/m²K) — aluminum without thermal break."""

ROOF_RATIO_THRESHOLD = 0.50
"""Minimum exposed_roof_area / flat_floor_area ratio to promote to 'top' floor type."""

ROOF_TILT_THRESHOLD_DEG = 10.0
"""Surfaces with tilt < this value are classified as horizontal roof."""

# ── Surface classification by tilt angle ─────────────────────────────────────

TILT_ROOF_MAX_DEG = 30.0
"""Surfaces with tilt < 30° are Roof."""

TILT_FLOOR_MIN_DEG = 150.0
"""Surfaces with tilt > 150° are Floor."""

TILT_WALL_MIN_DEG = 45.0
"""Vertical surfaces (tilt ≥ 45°) used in WWR denominator."""

# ── Simulation ───────────────────────────────────────────────────────────────

SIMULATION_TIMEOUT_S = 3600
"""Default EnergyPlus simulation timeout (seconds)."""

# ── EPW climate zone heuristics ──────────────────────────────────────────────

HIGHLAND_ELEVATION_M = 400.0
"""Elevation threshold for Zone C (highland) classification."""

HOT_ARID_LATITUDE_DEG = 30.5
"""Latitude threshold — below this → Zone B (hot arid south)."""

# ── Reference U-values — air film resistance ─────────────────────────────────

R_FILMS_M2K_PER_W = 0.17
"""Combined inside + outside air film resistance (m²K/W)."""
