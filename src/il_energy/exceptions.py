"""Custom exceptions for the il-energy package."""

from __future__ import annotations


class ILEnergyError(Exception):
    """Base exception for all il-energy errors."""


class SimulationError(ILEnergyError):
    """EnergyPlus simulation failed."""

    def __init__(self, message: str, return_code: int | None = None, stderr: str = ""):
        super().__init__(message)
        self.return_code = return_code
        self.stderr = stderr


class IDFError(ILEnergyError):
    """Error parsing or modifying an IDF file."""


class SQLParseError(ILEnergyError):
    """Error parsing EnergyPlus SQL output."""


class ConfigError(ILEnergyError):
    """Configuration error (missing EP installation, etc.)."""
