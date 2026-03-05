"""EnergyPlus CLI subprocess wrapper."""

from __future__ import annotations

import subprocess
from pathlib import Path

from il_energy.config import SIMULATION_TIMEOUT, EnergyPlusConfig
from il_energy.exceptions import SimulationError
from il_energy.models import SimulationRequest, SimulationResult
from il_energy.simulation.idf_parser import ensure_sql_output


def run_simulation(
    request: SimulationRequest,
    config: EnergyPlusConfig | None = None,
    timeout: int = SIMULATION_TIMEOUT,
) -> SimulationResult:
    """Run an EnergyPlus simulation and return the result.

    The IDF is automatically prepared (Output:SQLite injected if missing).
    A copy is made — the original IDF is never modified.
    """
    config = config or EnergyPlusConfig()

    idf_path = Path(request.idf_path).resolve()
    epw_path = Path(request.epw_path).resolve()
    output_dir = Path(request.output_dir).resolve()

    if not idf_path.is_file():
        raise SimulationError(f"IDF file not found: {idf_path}")
    if not epw_path.is_file():
        raise SimulationError(f"EPW file not found: {epw_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # Prepare IDF (inject output objects if missing)
    prepared_idf = ensure_sql_output(idf_path)

    cmd = [
        str(config.binary),
        "-w", str(epw_path),
        "-d", str(output_dir),
        "-a",   # annual simulation
        "-x",   # run ExpandObjects
        "-r",   # run ReadVarsESO
        str(prepared_idf),
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise SimulationError(
            f"EnergyPlus timed out after {timeout}s",
            stderr=str(e),
        ) from e

    sql_path = output_dir / "eplusout.sql"

    result = SimulationResult(
        success=proc.returncode == 0 and sql_path.is_file(),
        return_code=proc.returncode,
        output_dir=output_dir,
        sql_path=sql_path if sql_path.is_file() else None,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )

    if not result.success:
        err_file = output_dir / "eplusout.err"
        err_content = ""
        if err_file.is_file():
            err_content = err_file.read_text(errors="replace")
        raise SimulationError(
            f"EnergyPlus failed (exit code {proc.returncode})",
            return_code=proc.returncode,
            stderr=err_content or proc.stderr,
        )

    return result
