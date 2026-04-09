"""EnergyPlus CLI subprocess wrapper."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Optional

from il_energy.config import SIMULATION_TIMEOUT, EnergyPlusConfig
from il_energy.exceptions import SimulationError
from il_energy.models import SimulationRequest, SimulationResult
from il_energy.simulation.idf_parser import ensure_sql_output


def run_simulation(
    request: SimulationRequest,
    config: EnergyPlusConfig | None = None,
    timeout: int = SIMULATION_TIMEOUT,
    stdout_callback: Optional[Callable[[str], None]] = None,
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

    stdout_lines: list[str] = []
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(Path(config.binary).parent),
        )
        for line in proc.stdout:  # type: ignore[union-attr]
            stdout_lines.append(line)
            if stdout_callback:
                stdout_callback(line)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise SimulationError(f"EnergyPlus timed out after {timeout}s")

    stdout_text = "".join(stdout_lines)
    sql_path = output_dir / "eplusout.sql"

    result = SimulationResult(
        success=proc.returncode == 0 and sql_path.is_file(),
        return_code=proc.returncode,
        output_dir=output_dir,
        sql_path=sql_path if sql_path.is_file() else None,
        stdout=stdout_text,
        stderr="",
    )

    if not result.success:
        err_file = output_dir / "eplusout.err"
        err_content = err_file.read_text(errors="replace") if err_file.is_file() else ""
        raise SimulationError(
            f"EnergyPlus failed (exit code {proc.returncode})",
            return_code=proc.returncode,
            stderr=err_content or stdout_text,
        )

    return result
