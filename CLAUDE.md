# CLAUDE.md — il-energy project guide

## Project overview

Israeli Energy Compliance Engine for SI 5282 (ת"י 5282 Part 1, 2024). Wraps EnergyPlus as a black-box simulation tool, extracts HVAC metrics, and computes residential energy ratings (A+ through F) per the Israeli building standard.

**Repository:** `git@github.com:DavidBerrebi/il-energy.git`

## Build & install

```bash
# Core install
pip install -e .

# With desktop GUI
pip install -e ".[gui]"

# With web interface
pip install -e ".[web]"

# Dev tools (pytest, ruff)
pip install -e ".[dev]"
```

Requires Python 3.9+ and EnergyPlus 25.2.0 at `/Applications/EnergyPlus-25-2-0/`.

## Commands

```bash
# Main residential rating (the primary workflow)
il-energy compare-residential --idf FILE.idf --epw FILE.epw --output-dir ./output/project

# Raw EnergyPlus simulation + metrics extraction
il-energy run --idf FILE.idf --epw FILE.epw --output-dir ./output

# Parse existing SQL output without re-running EP
il-energy parse --sql path/to/eplusout.sql

# Desktop GUI
il-energy-gui

# Web interface (FastAPI on port 8000)
il-energy-web
```

## Testing

```bash
# Run all tests (139 unit tests, ~2 seconds)
pytest

# Run with coverage
pytest --cov=il_energy

# Integration tests (require EnergyPlus installed)
pytest -m integration

# Single test file
pytest tests/test_rating/test_calculator.py -v
```

Test fixture: `tests/fixtures/sample_eplusout.sql` (from 1ZoneUncontrolled example).

All tests must pass before committing. No tests should be skipped without a marker.

## Code style

- **Python 3.9 compatible** — no `X | None` union syntax, use `Optional[X]` in type hints and Pydantic models
- **Pydantic v2** for all data models (`src/il_energy/models.py`)
- **Click** for CLI (`src/il_energy/cli.py`)
- **No linter enforced yet** — ruff is available but not in CI. Follow existing patterns.
- Imports: stdlib → third-party → local, with `from __future__ import annotations` at top of each module
- IDF comment syntax: use `!` not `\!` — use heredoc not printf when appending to IDF files
- Energy units: SQL end-uses are in GJ, convert with `* 277.778` for kWh

## Project structure

```
src/il_energy/
├── cli.py                  # CLI entry points (Click groups)
├── gui.py                  # Desktop Tkinter GUI
├── config.py               # EnergyPlus path config + zone detection
├── constants.py            # SI 5282 constants (COP, thresholds, ref window values)
├── models.py               # Pydantic data models
├── exceptions.py           # Custom exceptions
├── web/                    # FastAPI web interface
│   ├── app.py              # FastAPI app + uvicorn entry point
│   ├── routes.py           # API endpoints
│   ├── jobs.py             # Background job manager
│   ├── templates/          # Jinja2 HTML templates
│   └── static/             # CSS + JS
├── simulation/             # EnergyPlus runner, IDF parsing, SQL parsing
├── postprocessing/         # Metrics extraction, zone→flat aggregation
├── rating/                 # IP computation, grade lookup
├── reference/              # Reference building/box generation
├── envelope/               # H-value, Report H, Report 1045
├── analysis/               # Window analysis
├── report/                 # PDF/Markdown/CSV report generation
├── adapters/               # Format adapters
├── rules/                  # Compliance rules
└── utils/                  # Shared utilities (zone naming)

standards/si5282/           # JSON config files (thresholds, EPref values, etc.)
tests/                      # 139 unit tests
```

## Key architectural patterns

- **CLI functions are decomposed** — `cli.py` calls helper functions (`_preprocess_proposed_idf`, `_run_proposed_and_aggregate`, etc.) that can be reused from GUI and web
- **GUI and web both call `compare_residential.callback()` directly** — they monkey-patch `click.echo` to capture logs
- **IDF version auto-conversion** — `idf_parser.py` detects EP version and delegates to `idf_v89_converter.py`
- **EPref can be tabulated or simulated** — `ep_ref_values.json` has per-zone values; fallback is 12-16 reference-box EP runs
- **Zone aggregation** — EnergyPlus thermal zones are grouped into residential flats by naming convention (e.g., `00X1:LIVING`)

## Climate zones

Zone A = Mediterranean coastal (Tel Aviv, Haifa) → Standard Part 1 Zone A
Zone B = Hot-arid desert (Eilat, Beersheba) → Standard Part 1 Zone D
Zone C = Highland (Jerusalem, Safed) → Standard Part 1 Zone C

Auto-detected from EPW filename via WMO station code.

## Weather files

Located at `/Users/davidberrebi/Desktop/EnergyGreen/ClimateIsrael/*.epw` — not committed to repo.

## Git conventions

- Commit messages: `type: description` (e.g., `feat:`, `fix:`, `refactor:`, `test:`, `docs:`)
- Branch: `main` is the primary branch
- Don't commit: output files, EPW files, `.claude/` directory, EnergyPlus transient outputs
- The `.gitignore` already covers these patterns

## Common gotchas

- 1ZoneUncontrolled has 0 conditioned area — normalizer returns zeros correctly (not a bug)
- EP 25.2 latent cooling is excluded via sensible-only SQL strategy (matches EP 9.4 behavior)
- `Output:SQLite, SimpleAndTabular;` must be injected into IDF if missing — `idf_parser.py` handles this
- Ground-floor EPdes runs ~18% higher in EP 25.2 vs 9.4 due to ground contact thermal model change (irreducible EP version gap)
