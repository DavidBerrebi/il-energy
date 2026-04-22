"""API routes for the EVERGREEN web interface."""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse

from il_energy.web.jobs import JobManager, JobStatus

router = APIRouter(prefix="/api")

# Injected by app.py at startup
job_manager: JobManager = None  # type: ignore[assignment]
epw_dir: Path = None  # type: ignore[assignment]


@router.get("/epw-files")
def list_epw_files():
    """List available EPW weather files."""
    if not epw_dir or not epw_dir.is_dir():
        return []

    files = []
    for p in sorted(epw_dir.glob("*.epw")):
        # Extract city name from filename
        # e.g. "ISR_TA_Tel.Aviv-Sde.Dov_.AP_.401762_..." → "Tel Aviv"
        name = p.stem
        parts = name.split("_")
        # Try to find the city part (usually 3rd segment)
        display = name
        if len(parts) >= 3:
            city_part = parts[2].replace(".", " ").replace("-", " ").split()
            if city_part:
                display = " ".join(city_part[:3])

        files.append({"path": str(p), "display_name": display, "filename": p.name})

    return files


@router.get("/jobs")
def list_jobs():
    """List all jobs."""
    return job_manager.list_jobs()


@router.post("/jobs")
async def create_job(
    idf: UploadFile = File(...),
    epw_path: str = Form(...),
    climate_zone: str = Form("auto"),
):
    """Upload IDF and start a simulation job."""
    if not idf.filename or not idf.filename.lower().endswith(".idf"):
        raise HTTPException(400, "File must be an .idf file")

    # Validate EPW path exists
    if not Path(epw_path).is_file():
        raise HTTPException(400, f"EPW file not found: {epw_path}")

    content = await idf.read()
    zone = None if climate_zone == "auto" else climate_zone

    job = job_manager.create_job(
        idf_filename=idf.filename,
        idf_content=content,
        epw_path=epw_path,
        climate_zone=zone,
    )

    return {"job_id": job.id, "status": job.status.value}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    """Get job status and result summary."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    result = {
        "id": job.id,
        "status": job.status.value,
        "created_at": job.created_at,
        "idf_filename": job.idf_filename,
        "climate_zone": job.climate_zone,
        "error": job.error,
    }

    if job.result_json:
        r = job.result_json
        result["summary"] = {
            "grade": r.get("grade", {}).get("grade"),
            "grade_name": r.get("grade", {}).get("name_en"),
            "ep_des_kwh_m2": r.get("ep_des_kwh_m2"),
            "ep_ref_kwh_m2": r.get("ep_ref_kwh_m2"),
            "ip_percent": r.get("ip_percent"),
            "conditioned_area_m2": r.get("conditioned_area_m2"),
            "climate_zone": r.get("climate_zone"),
            "unit_ratings": r.get("unit_ratings", []),
        }

    return result


@router.get("/jobs/{job_id}/logs")
async def stream_logs(job_id: str):
    """SSE stream of job log output."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    async def event_stream():
        offset = 0
        while True:
            new_lines = job.get_logs_from(offset)
            if new_lines:
                for line in new_lines:
                    # SSE format: each line prefixed with "data: "
                    # Multi-line messages need each line prefixed
                    for sub in line.splitlines():
                        yield f"data: {sub}\n"
                    yield "\n"
                offset += len(new_lines)

            if job.status in (JobStatus.COMPLETE, JobStatus.FAILED):
                yield f"event: done\ndata: {job.status.value}\n\n"
                break

            await asyncio.sleep(0.3)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/jobs/{job_id}/results")
def list_results(job_id: str):
    """List output files for a completed job."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    files = []
    output_dir = job.output_dir

    # Collect relevant output files (skip raw EP outputs and input dir)
    skip_extensions = {".eso", ".mtr", ".csv", ".bnd", ".edd", ".eio",
                       ".end", ".err", ".mdd", ".mtd", ".rdd", ".shd",
                       ".rvaudit", ".audit", ".dxf"}
    skip_names = {"eplusmtr.csv", "eplusout.csv", "eplustbl.csv",
                  "eplusout.sql", "sqlite.err"}

    for p in sorted(output_dir.rglob("*")):
        if not p.is_file():
            continue
        # Skip input directory and raw EP files
        rel = p.relative_to(output_dir)
        parts = rel.parts
        if parts[0] in ("input", "proposed", "reference", "reference_boxes"):
            continue
        if p.suffix in skip_extensions and p.name not in ("units.csv", "windows.csv",
                                                           "h_values.csv", "grade_comparison.csv"):
            continue
        if p.name in skip_names:
            continue

        category = "report"
        if p.suffix == ".pdf":
            category = "pdf"
        elif p.suffix == ".json":
            category = "data"
        elif p.suffix == ".csv":
            category = "data"
        elif p.suffix in (".html", ".md"):
            category = "report"

        display = str(rel)
        files.append({
            "filename": display,
            "category": category,
            "size_bytes": p.stat().st_size,
        })

    return files


@router.get("/jobs/{job_id}/files/{filename:path}")
def download_file(job_id: str, filename: str):
    """Serve an output file."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    file_path = (job.output_dir / filename).resolve()

    # Security: ensure file is within job output dir
    if not str(file_path).startswith(str(job.output_dir.resolve())):
        raise HTTPException(403, "Access denied")

    if not file_path.is_file():
        raise HTTPException(404, f"File not found: {filename}")

    media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

    # PDFs should open inline in browser
    if file_path.suffix == ".pdf":
        return FileResponse(file_path, media_type="application/pdf",
                            headers={"Content-Disposition": f"inline; filename=\"{file_path.name}\""})

    return FileResponse(file_path, media_type=media_type, filename=file_path.name)
