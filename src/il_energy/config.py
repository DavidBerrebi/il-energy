"""Global configuration for EnergyPlus paths and defaults."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def _find_energyplus() -> Path | None:
    """Auto-detect EnergyPlus installation path."""
    # Check environment variable first
    env_path = os.environ.get("ENERGYPLUS_DIR")
    if env_path:
        p = Path(env_path)
        if p.is_dir():
            return p

    # macOS default locations
    for candidate in Path("/Applications").glob("EnergyPlus-*"):
        if candidate.is_dir():
            return candidate

    # Check if energyplus is on PATH
    ep = shutil.which("energyplus")
    if ep:
        return Path(ep).parent

    return None


def _find_binary(ep_dir: Path) -> Path | None:
    """Find the energyplus binary within an installation directory."""
    for candidate in sorted(ep_dir.glob("energyplus-*"), reverse=True):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    # Try plain 'energyplus'
    plain = ep_dir / "energyplus"
    if plain.is_file() and os.access(plain, os.X_OK):
        return plain
    return None


class EnergyPlusConfig:
    """Configuration for EnergyPlus installation."""

    def __init__(
        self,
        ep_dir: Path | str | None = None,
        binary: Path | str | None = None,
    ):
        if ep_dir:
            self._ep_dir = Path(ep_dir)
        else:
            detected = _find_energyplus()
            if detected is None:
                raise FileNotFoundError(
                    "EnergyPlus installation not found. "
                    "Set ENERGYPLUS_DIR environment variable or pass ep_dir."
                )
            self._ep_dir = detected

        if binary:
            self._binary = Path(binary)
        else:
            found = _find_binary(self._ep_dir)
            if found is None:
                raise FileNotFoundError(
                    f"EnergyPlus binary not found in {self._ep_dir}"
                )
            self._binary = found

    @property
    def ep_dir(self) -> Path:
        return self._ep_dir

    @property
    def binary(self) -> Path:
        return self._binary

    @property
    def idd_path(self) -> Path:
        return self._ep_dir / "Energy+.idd"

    @property
    def weather_dir(self) -> Path:
        return self._ep_dir / "WeatherData"

    @property
    def example_dir(self) -> Path:
        return self._ep_dir / "ExampleFiles"


from il_energy.constants import HIGHLAND_ELEVATION_M, HOT_ARID_LATITUDE_DEG, SIMULATION_TIMEOUT_S

# Default timeout for EnergyPlus simulations (seconds)
SIMULATION_TIMEOUT = SIMULATION_TIMEOUT_S


# ── SI 5282 climate zone detection from EPW ───────────────────────────────────

# WMO station → SI 5282 zone (our A/B/C naming)
_WMO_ZONE_MAP = {
    # Zone A — Mediterranean coastal
    "401762": "A",  # Tel Aviv Sde Dov
    "401800": "A",  # Tel Aviv Ben Gurion
    "401550": "A",  # Haifa
    "401710": "A",  # Ashkelon
    # Zone B — Hot arid desert (Negev / Rift Valley)
    "401990": "B",  # Eilat-Hozman
    "401920": "B",  # Sedom / Dead Sea
    "401880": "B",  # Beersheba
    # Zone C — Highland
    "401839": "C",  # Jerusalem center
    "401830": "C",  # Jerusalem
    "401410": "C",  # Safed (highland north)
}


def detect_zone_from_epw(epw_path: "Path") -> str:
    """Detect SI 5282 climate zone (A/B/C) from an EPW file's LOCATION header.

    Priority:
    1. Known WMO station ID lookup
    2. Heuristic from latitude + elevation:
       elevation > 400 m → C  (highland: Jerusalem, Safed)
       latitude < 30.5°N → A  (hot arid south: Eilat, Negev)
       otherwise → B           (coastal / central lowlands)

    Returns "B" if the file cannot be read.
    """
    try:
        with open(epw_path, encoding="latin-1") as f:
            first_line = f.readline().strip()
    except OSError:
        return "B"

    if not first_line.upper().startswith("LOCATION"):
        return "B"

    parts = first_line.split(",")
    # LOCATION,City,State,Country,DataSource,WMO,Lat,Lon,TZ,Elevation
    if len(parts) < 10:
        return "B"

    wmo = parts[5].strip()
    if wmo in _WMO_ZONE_MAP:
        return _WMO_ZONE_MAP[wmo]

    try:
        lat = float(parts[6].strip())
        elev = float(parts[9].strip())
    except (ValueError, IndexError):
        return "B"

    if elev > HIGHLAND_ELEVATION_M:
        return "C"
    if lat < HOT_ARID_LATITUDE_DEG:
        return "B"   # hot-arid south (Negev / Rift Valley)
    return "A"       # coastal / central lowlands default
