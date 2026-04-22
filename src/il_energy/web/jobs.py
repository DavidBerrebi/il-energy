"""Job manager for background EnergyPlus simulations."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class JobInfo:
    id: str
    status: JobStatus
    created_at: str
    idf_filename: str
    epw_path: str
    climate_zone: Optional[str]
    output_dir: Path
    log_lines: list[str] = field(default_factory=list)
    error: Optional[str] = None
    result_json: Optional[dict] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def append_log(self, text: str) -> None:
        with self._lock:
            self.log_lines.append(text)

    def log_count(self) -> int:
        with self._lock:
            return len(self.log_lines)

    def get_logs_from(self, offset: int) -> list[str]:
        with self._lock:
            return list(self.log_lines[offset:])


class JobManager:
    """Manages simulation jobs with background execution."""

    def __init__(self, jobs_dir: Path) -> None:
        self.jobs_dir = jobs_dir
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, JobInfo] = {}
        self._lock = threading.Lock()

    def create_job(
        self,
        idf_filename: str,
        idf_content: bytes,
        epw_path: str,
        climate_zone: Optional[str] = None,
    ) -> JobInfo:
        job_id = uuid.uuid4().hex[:12]
        output_dir = self.jobs_dir / job_id
        input_dir = output_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        # Save uploaded IDF
        idf_path = input_dir / idf_filename
        idf_path.write_bytes(idf_content)

        job = JobInfo(
            id=job_id,
            status=JobStatus.QUEUED,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            idf_filename=idf_filename,
            epw_path=epw_path,
            climate_zone=climate_zone,
            output_dir=output_dir,
        )

        with self._lock:
            self._jobs[job_id] = job

        # Start simulation in background thread
        thread = threading.Thread(
            target=self._run_job, args=(job,), daemon=True
        )
        thread.start()

        return job

    def get_job(self, job_id: str) -> Optional[JobInfo]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[dict]:
        with self._lock:
            jobs = list(self._jobs.values())
        return [
            {
                "id": j.id,
                "status": j.status.value,
                "created_at": j.created_at,
                "idf_filename": j.idf_filename,
                "climate_zone": j.climate_zone,
                "grade": (j.result_json or {}).get("grade", {}).get("grade"),
            }
            for j in sorted(jobs, key=lambda j: j.created_at, reverse=True)
        ]

    def _run_job(self, job: JobInfo) -> None:
        job.status = JobStatus.RUNNING
        job.append_log(
            f"Starting simulation: {job.idf_filename}\n"
            f"EPW: {job.epw_path}\n"
            f"Output: {job.output_dir}\n\n"
        )

        import click

        original_echo = click.echo

        def _capture_echo(message=None, file=None, nl=True, err=False, **kw):
            text = str(message) if message is not None else ""
            if nl:
                text += "\n"
            job.append_log(text)

        try:
            click.echo = _capture_echo  # type: ignore[assignment]

            from il_energy.cli import compare_residential

            idf_path = str(job.output_dir / "input" / job.idf_filename)
            compare_residential.callback(
                idf=idf_path,
                epw=job.epw_path,
                output_dir=str(job.output_dir),
                zone=job.climate_zone,
                simulate_epref=False,
            )

            # Load result JSON
            rating_path = job.output_dir / "residential_rating.json"
            if rating_path.exists():
                with open(rating_path, encoding="utf-8") as f:
                    job.result_json = json.load(f)

            job.status = JobStatus.COMPLETE
            job.append_log("\nSimulation complete.\n")

        except SystemExit:
            job.status = JobStatus.FAILED
            job.error = "Simulation exited with errors (see log)"
            job.append_log("\nSimulation finished with errors.\n")
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = str(exc)
            job.append_log(f"\nError: {exc}\n")
        finally:
            click.echo = original_echo  # type: ignore[assignment]
