"""FastAPI application for the EVERGREEN web interface."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request

from il_energy.web.jobs import JobManager
from il_energy.web import routes

# Paths
_WEB_DIR = Path(__file__).parent
_TEMPLATES_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # ClaudeCodeProj/
_JOBS_DIR = _PROJECT_ROOT / "output" / "web_jobs"
_EPW_DIR = Path("/Users/davidberrebi/Desktop/EnergyGreen/ClimateIsrael")

app = FastAPI(title="EVERGREEN Energy Simulator")

# Static files and templates
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Initialize job manager and inject into routes
_job_manager = JobManager(_JOBS_DIR)
routes.job_manager = _job_manager
routes.epw_dir = _EPW_DIR

# Include API routes
app.include_router(routes.router)


@app.get("/")
async def index(request: Request):
    """Serve the main page."""
    return templates.TemplateResponse(request, "index.html")


def main() -> None:
    """Entry point for il-energy-web command."""
    import uvicorn
    print("EVERGREEN Energy Simulator — Web Interface")
    print("  Local:   http://localhost:8000")
    print("  Network: http://0.0.0.0:8000")
    print("  Docs:    http://localhost:8000/docs")
    print()
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
