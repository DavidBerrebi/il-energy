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


# Default timeout for EnergyPlus simulations (seconds)
SIMULATION_TIMEOUT = 3600
