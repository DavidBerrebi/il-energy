"""Parse EnergyPlus SQLite output (eplusout.sql)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from il_energy.exceptions import SQLParseError
from il_energy.models import (
    BuildingArea,
    ConstructionAssembly,
    EnergyEndUse,
    EnvelopeSurface,
    MaterialLayer,
    NormalizedMetrics,
    SimulationMetadata,
    UnmetHours,
    WindowSurface,
    ZoneEnergy,
)

# Joules to kWh conversion
GJ_TO_KWH = 277.778  # 1 GJ = 277.778 kWh


def _safe_float(value: str | None, default: float = 0.0) -> float:
    """Convert a string value to float, returning default on failure."""
    if value is None:
        return default
    try:
        return float(value.strip())
    except (ValueError, AttributeError):
        return default


class SQLParser:
    """Parse an EnergyPlus eplusout.sql file."""

    def __init__(self, sql_path: Path | str):
        self.sql_path = Path(sql_path)
        if not self.sql_path.is_file():
            raise SQLParseError(f"SQL file not found: {self.sql_path}")
        self._conn = sqlite3.connect(str(self.sql_path))
        self._conn.row_factory = sqlite3.Row

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _query_tabular(
        self,
        report_name: str,
        table_name: str,
        row_name: str | None = None,
        column_name: str | None = None,
    ) -> list[sqlite3.Row]:
        """Query TabularDataWithStrings with filters."""
        sql = (
            "SELECT * FROM TabularDataWithStrings "
            "WHERE ReportName=? AND TableName=?"
        )
        params: list[str] = [report_name, table_name]

        if row_name is not None:
            sql += " AND RowName=?"
            params.append(row_name)
        if column_name is not None:
            sql += " AND ColumnName=?"
            params.append(column_name)

        try:
            return self._conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as e:
            raise SQLParseError(f"SQL query failed: {e}") from e

    def _get_tabular_value(
        self,
        report_name: str,
        table_name: str,
        row_name: str,
        column_name: str,
    ) -> str | None:
        """Get a single value from TabularDataWithStrings."""
        rows = self._query_tabular(report_name, table_name, row_name, column_name)
        if rows:
            return rows[0]["Value"]
        return None

    # --- Metadata ---

    def parse_metadata(self) -> SimulationMetadata:
        """Extract simulation metadata."""
        try:
            row = self._conn.execute(
                "SELECT * FROM Simulations LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return SimulationMetadata()

        if row is None:
            return SimulationMetadata()

        version_str = row["EnergyPlusVersion"] if "EnergyPlusVersion" in row.keys() else ""
        timestamp = row["TimeStamp"] if "TimeStamp" in row.keys() else ""

        return SimulationMetadata(
            ep_version=version_str,
            timestamp=timestamp,
        )

    # --- Building Area ---

    def parse_building_area(self) -> BuildingArea:
        """Extract building areas from the summary report."""
        report = "AnnualBuildingUtilityPerformanceSummary"
        table = "Building Area"

        total = _safe_float(self._get_tabular_value(report, table, "Total Building Area", "Area"))
        cond = _safe_float(self._get_tabular_value(report, table, "Net Conditioned Building Area", "Area"))
        uncond = _safe_float(self._get_tabular_value(report, table, "Unconditioned Building Area", "Area"))

        return BuildingArea(total_m2=total, conditioned_m2=cond, unconditioned_m2=uncond)

    # --- Site / Source Energy ---

    def _parse_energy_gj(self, row_name: str) -> float:
        """Read an energy value from Site and Source Energy table, return GJ.

        Handles both kWh and GJ units stored in the SQL (EP varies by output settings).
        """
        rows = self._query_tabular(
            "AnnualBuildingUtilityPerformanceSummary",
            "Site and Source Energy",
            row_name,
            "Total Energy",
        )
        if not rows:
            return 0.0
        r = rows[0]
        value = _safe_float(r["Value"])
        units = (r["Units"] or "").strip()
        if units == "kWh":
            return value / GJ_TO_KWH  # convert kWh → GJ
        return value  # assume GJ

    def parse_site_energy_gj(self) -> float:
        """Total site energy in GJ."""
        return self._parse_energy_gj("Total Site Energy")

    def parse_source_energy_gj(self) -> float:
        """Total source energy in GJ."""
        return self._parse_energy_gj("Total Source Energy")

    # --- End Uses ---

    def parse_end_uses(self) -> EnergyEndUse:
        """Extract end-use energy breakdown."""
        report = "AnnualBuildingUtilityPerformanceSummary"
        table = "End Uses"

        def _get_enduse(row_name: str) -> float:
            """Sum across all fuel types for an end use.

            Filters by energy units only (GJ or kWh). Skips peak demand rows (W).
            Converts GJ → kWh; passes kWh through as-is.
            """
            rows = self._query_tabular(report, table, row_name)
            total_kwh = 0.0
            for r in rows:
                units = (r["Units"] or "").strip()
                if units == "GJ":
                    total_kwh += _safe_float(r["Value"]) * GJ_TO_KWH
                elif units == "kWh":
                    total_kwh += _safe_float(r["Value"])
                # skip W, W/m2, and any other non-energy units
            return total_kwh

        heating = _get_enduse("Heating")
        cooling = _get_enduse("Cooling")
        int_lighting = _get_enduse("Interior Lighting")
        ext_lighting = _get_enduse("Exterior Lighting")
        int_equipment = _get_enduse("Interior Equipment")
        fans = _get_enduse("Fans")
        pumps = _get_enduse("Pumps")
        heat_rejection = _get_enduse("Heat Rejection")
        water = _get_enduse("Water Systems")

        total = heating + cooling + int_lighting + ext_lighting + int_equipment + fans + pumps + heat_rejection + water

        return EnergyEndUse(
            heating_kwh=heating,
            cooling_kwh=cooling,
            interior_lighting_kwh=int_lighting,
            exterior_lighting_kwh=ext_lighting,
            interior_equipment_kwh=int_equipment,
            fans_kwh=fans,
            pumps_kwh=pumps,
            heat_rejection_kwh=heat_rejection,
            water_systems_kwh=water,
            total_kwh=total,
        )

    # --- Envelope: Opaque Surfaces ---

    def parse_opaque_surfaces(self) -> list[EnvelopeSurface]:
        """Extract opaque exterior and semi-exterior surface data."""
        report = "EnvelopeSummary"
        result = []

        for table, adjacency in [("Opaque Exterior", "Exterior"), ("Opaque Semi-Exterior", "Semi-Exterior")]:
            rows = self._query_tabular(report, table)
            surfaces: dict[str, dict[str, str]] = {}
            for r in rows:
                name = r["RowName"]
                if name.startswith("Total") or name.startswith("North Total") or name.startswith("Non-North"):
                    continue
                if name not in surfaces:
                    surfaces[name] = {}
                surfaces[name][r["ColumnName"]] = r["Value"]

            for name, data in surfaces.items():
                result.append(EnvelopeSurface(
                    name=name,
                    construction=data.get("Construction", ""),
                    zone=data.get("Zone", ""),
                    adjacency=adjacency,
                    u_factor_w_m2k=_safe_float(data.get("U-Factor with Film")) if "U-Factor with Film" in data else None,
                    gross_area_m2=_safe_float(data.get("Gross Area")) if "Gross Area" in data else None,
                    azimuth_deg=_safe_float(data.get("Azimuth")) if "Azimuth" in data else None,
                    tilt_deg=_safe_float(data.get("Tilt")) if "Tilt" in data else None,
                ))

        return result

    # --- Envelope: Windows ---

    def parse_windows(self) -> list[WindowSurface]:
        """Extract exterior fenestration data."""
        report = "EnvelopeSummary"
        table = "Exterior Fenestration"

        rows = self._query_tabular(report, table)
        surfaces: dict[str, dict[str, str]] = {}
        for r in rows:
            name = r["RowName"]
            if name.startswith("Total") or name.startswith("North Total") or name.startswith("Non-North"):
                continue
            if name not in surfaces:
                surfaces[name] = {}
            surfaces[name][r["ColumnName"]] = r["Value"]

        result = []
        for name, data in surfaces.items():
            result.append(WindowSurface(
                name=name,
                construction=data.get("Construction", ""),
                zone=data.get("Zone", ""),
                glass_area_m2=_safe_float(data.get("Glass Area")) if "Glass Area" in data else None,
                frame_area_m2=_safe_float(data.get("Frame and Divider Area")) if "Frame and Divider Area" in data else None,
                u_factor_w_m2k=_safe_float(data.get("Glass U-Factor")) if "Glass U-Factor" in data else None,
                shgc=_safe_float(data.get("Glass SHGC")) if "Glass SHGC" in data else None,
                visible_transmittance=_safe_float(data.get("Glass Visible Transmittance")) if "Glass Visible Transmittance" in data else None,
                azimuth_deg=_safe_float(data.get("Azimuth")) if "Azimuth" in data else None,
                parent_surface=data.get("Parent Surface", ""),
            ))
        return result

    # --- Unmet Hours ---

    def parse_unmet_hours(self) -> UnmetHours:
        """Extract comfort/setpoint unmet hours."""
        report = "AnnualBuildingUtilityPerformanceSummary"
        table = "Comfort and Setpoint Not Met Summary"

        heating = _safe_float(self._get_tabular_value(
            report, table,
            "Time Setpoint Not Met During Occupied Heating",
            "Facility",
        ))
        cooling = _safe_float(self._get_tabular_value(
            report, table,
            "Time Setpoint Not Met During Occupied Cooling",
            "Facility",
        ))

        return UnmetHours(
            heating_unmet_hours=heating,
            cooling_unmet_hours=cooling,
            total_unmet_hours=heating + cooling,
        )

    # --- Construction Assemblies (for Report 1045) ---

    def parse_construction_assemblies(self) -> list[ConstructionAssembly]:
        """Extract construction assemblies with material layers from SQL.

        Queries the Constructions, ConstructionLayers, and Materials tables
        to build a layer-by-layer breakdown of each exterior/semi-exterior
        opaque construction used in the building.

        Surface class (Wall/Roof/Floor/Ceiling) and adjacency are derived
        from the Surfaces table tilt and boundary condition.

        Semi-exterior detection: surfaces with ExtBoundCond > 0 whose
        boundary partner is in a different zone (typically a CORE zone)
        are classified as semi-exterior rather than interior.
        """
        # ── Collect unique construction + surface info ────────────────────────
        # ExtBoundCond: 0=Exterior, -1=Ground, >0=surface index of partner
        try:
            rows = self._conn.execute("""
                SELECT
                    c.ConstructionIndex,
                    c.Name AS cname,
                    c.Uvalue,
                    s.Tilt,
                    s.ExtBoundCond,
                    s.ZoneIndex,
                    s.SurfaceIndex
                FROM Surfaces s
                JOIN Constructions c ON s.ConstructionIndex = c.ConstructionIndex
                WHERE c.TypeIsWindow = 0
                  AND c.Name NOT LIKE '%!_REV' ESCAPE '!'
                  AND c.Name NOT IN ('IRTSURFACE', 'LINEARBRIDGINGCONSTRUCTION')
                  AND s.HeatTransferSurf = 1
            """).fetchall()
        except sqlite3.OperationalError:
            return []

        # Build zone index → zone name map for semi-exterior detection
        zone_names: dict[int, str] = {}
        try:
            for zr in self._conn.execute("SELECT ZoneIndex, ZoneName FROM Zones").fetchall():
                zone_names[zr["ZoneIndex"]] = zr["ZoneName"]
        except sqlite3.OperationalError:
            pass

        # Build surface index → zone index map
        surf_zone: dict[int, int] = {}
        try:
            for sr in self._conn.execute("SELECT SurfaceIndex, ZoneIndex FROM Surfaces").fetchall():
                surf_zone[sr["SurfaceIndex"]] = sr["ZoneIndex"]
        except sqlite3.OperationalError:
            pass

        # Known interior-only constructions (both sides conditioned, same type)
        _SKIP_NAMES = {"_INTPARTITION", "_INTFLOOR_REVERSED"}

        # Determine per-construction: best adjacency classification
        # Priority: Exterior > Ground > Semi-Exterior; skip pure Interior
        constr_info: dict[str, dict] = {}  # cname_upper → {ci, tilt, adjacency}

        for row in rows:
            cname = row["cname"]
            cname_upper = cname.upper()
            if cname_upper in _SKIP_NAMES:
                continue

            ext_bc = int(row["ExtBoundCond"])
            tilt = float(row["Tilt"])

            if ext_bc == 0:
                adjacency = "Exterior"
            elif ext_bc == -1:
                adjacency = "Exterior"  # ground contact
            elif ext_bc > 0:
                # Check if partner surface is in a different zone
                partner_zone = surf_zone.get(ext_bc)
                this_zone = int(row["ZoneIndex"])
                if partner_zone is not None and partner_zone != this_zone:
                    # Different zone — semi-exterior if one side is CORE
                    this_name = zone_names.get(this_zone, "")
                    partner_name = zone_names.get(partner_zone, "")
                    if "CORE" in partner_name.upper() or "CORE" in this_name.upper():
                        adjacency = "Semi-Exterior"
                        # If this surface is in the CORE zone, flip tilt to
                        # represent the conditioned zone's perspective
                        if "CORE" in this_name.upper():
                            tilt = 180.0 - tilt if tilt <= 90 else tilt
                    else:
                        # Two conditioned zones — interior partition
                        continue
                else:
                    continue  # same zone or unknown — skip
            else:
                continue

            # Keep the most "exterior" classification per construction
            adj_priority = {"Exterior": 2, "Semi-Exterior": 1}
            existing = constr_info.get(cname_upper)
            if existing is None or adj_priority.get(adjacency, 0) > adj_priority.get(existing["adjacency"], 0):
                constr_info[cname_upper] = {
                    "cname": cname,
                    "ci": row["ConstructionIndex"],
                    "tilt": tilt,
                    "adjacency": adjacency,
                }

        assemblies = []
        for cname_upper, info in constr_info.items():
            tilt = info["tilt"]
            adjacency = info["adjacency"]

            # Determine surface class from tilt
            if 60 <= tilt <= 120:
                surface_class = "Wall"
            elif tilt < 60:
                surface_class = "Roof"
            else:
                surface_class = "Floor"

            # For semi-exterior ceilings (tilt < 60, semi-ext), classify as Ceiling
            if tilt < 60 and adjacency == "Semi-Exterior":
                surface_class = "Ceiling"

            # Query material layers
            try:
                layer_rows = self._conn.execute("""
                    SELECT cl.LayerIndex, m.Name, m.Thickness, m.Conductivity,
                           m.Density, m.Resistance
                    FROM ConstructionLayers cl
                    JOIN Materials m ON cl.MaterialIndex = m.MaterialIndex
                    WHERE cl.ConstructionIndex = ?
                    ORDER BY cl.LayerIndex
                """, (info["ci"],)).fetchall()
            except sqlite3.OperationalError:
                layer_rows = []

            layers: list[MaterialLayer] = []
            total_density_kg_m2 = 0.0
            total_resistance = 0.0

            for lr in layer_rows:
                thickness = float(lr["Thickness"])
                conductivity = float(lr["Conductivity"])
                density = float(lr["Density"])
                resistance = float(lr["Resistance"])
                density_kg_m2 = thickness * density

                layers.append(MaterialLayer(
                    name=lr["Name"],
                    thickness_m=thickness,
                    conductivity_w_mk=conductivity,
                    resistance_m2kw=resistance,
                    density_kg_m3=density,
                    calculated_density_kg_m2=density_kg_m2,
                ))
                total_density_kg_m2 += density_kg_m2
                total_resistance += resistance

            assemblies.append(ConstructionAssembly(
                name=info["cname"],
                surface_class=surface_class,
                adjacency=adjacency,
                layers=layers,
                calculated_density_kg_m2=total_density_kg_m2,
                calculated_resistance_m2kw=total_resistance,
            ))

        return assemblies

    # --- Zone-Level Energy (from ReportData) ---

    def parse_zone_energy(self) -> list[ZoneEnergy]:
        """Extract zone-level annual HVAC energy from ReportData tables.

        Supports two retrieval strategies (tried in order):
        1. Annual energy (J) variables: ``*Ideal Loads*Energy*``
        2. Run-Period averaged rate (W) variables: ``*Ideal Loads*Cooling/Heating Rate``
           Converted to kWh using avg_W × 8760 h / 1000.

        Zone floor area is taken from the ``Zones`` table when available,
        falling back to the Zone Summary tabular report.
        """
        # ── Build zone lookup (floor area from Zones table if present) ──────────
        zones: dict[str, ZoneEnergy] = {}
        try:
            zone_rows = self._conn.execute(
                "SELECT ZoneName, FloorArea FROM Zones"
            ).fetchall()
            for zr in zone_rows:
                name = zr["ZoneName"]
                zones[name.upper()] = ZoneEnergy(
                    zone_name=name,
                    floor_area_m2=_safe_float(str(zr["FloorArea"])),
                )
        except sqlite3.OperationalError:
            pass

        # Fall back: derive zones from tabular Zone Summary
        if not zones:
            try:
                tab_rows = self._conn.execute(
                    """SELECT RowName, Value FROM TabularDataWithStrings
                       WHERE ReportName='InputVerificationandResultsSummary'
                         AND TableName='Zone Summary'
                         AND ColumnName='Area'"""
                ).fetchall()
                for tr in tab_rows:
                    name = tr["RowName"]
                    # Skip aggregate summary rows
                    if name in ("Conditioned Total", "Unconditioned Total",
                                "Not Part of Total", "Total"):
                        continue
                    zones[name.upper()] = ZoneEnergy(
                        zone_name=name,
                        floor_area_m2=_safe_float(tr["Value"]),
                    )
            except sqlite3.OperationalError:
                return []

        if not zones:
            return []

        # ── Strategy 1: look for annual energy (J) variables ────────────────────
        try:
            rdd_energy = self._conn.execute(
                """SELECT ReportDataDictionaryIndex, KeyValue, Name
                   FROM ReportDataDictionary
                   WHERE Name LIKE '%Ideal Loads%Energy%'
                   AND IsMeter = 0"""
            ).fetchall()
        except sqlite3.OperationalError:
            rdd_energy = []

        if rdd_energy:
            for rdd in rdd_energy:
                key = rdd["KeyValue"].upper()
                var_name = rdd["Name"].upper()
                idx = rdd["ReportDataDictionaryIndex"]
                matched = next((z for z in zones if key.startswith(z)), None)
                if matched is None:
                    continue
                total_j = self._conn.execute(
                    "SELECT SUM(Value) FROM ReportData WHERE ReportDataDictionaryIndex=?",
                    (idx,),
                ).fetchone()[0] or 0.0
                total_kwh = total_j / 3_600_000.0
                if "HEATING" in var_name:
                    zones[matched].heating_kwh += total_kwh
                elif "COOLING" in var_name:
                    zones[matched].cooling_kwh += total_kwh
        else:
            # ── Strategy 2: Run-Period avg W → kWh ──────────────────────────────
            # Use SENSIBLE rates only to match EP 9.x / EVERGREEN methodology.
            # EP 25.2 reports latent dehumidification loads via the Total rate
            # that EP 9.x did not compute; using Sensible ensures consistency.
            # Variable names: "Zone Ideal Loads Supply Air Sensible Heating Rate" (W)
            #                 "Zone Ideal Loads Supply Air Sensible Cooling Rate" (W)
            # Stored as time-weighted average over run period → kWh = avg_W × 8760 / 1000
            try:
                rdd_rate = self._conn.execute(
                    """SELECT ReportDataDictionaryIndex, KeyValue, Name
                       FROM ReportDataDictionary
                       WHERE Name LIKE 'Zone Ideal Loads Supply Air Sensible%Rate'
                       AND ReportingFrequency = 'Run Period'
                       AND IsMeter = 0"""
                ).fetchall()
            except sqlite3.OperationalError:
                rdd_rate = []

            # EP 25.2 may not report "Sensible Heating Rate" — fall back to
            # "Total Heating Rate" for heating if no sensible heating vars found.
            has_sensible_heating = any(
                "HEATING" in r["Name"].upper() for r in rdd_rate
            )
            if not has_sensible_heating:
                try:
                    rdd_total_heat = self._conn.execute(
                        """SELECT ReportDataDictionaryIndex, KeyValue, Name
                           FROM ReportDataDictionary
                           WHERE Name LIKE 'Zone Ideal Loads Supply Air Total Heating Rate'
                           AND ReportingFrequency = 'Run Period'
                           AND IsMeter = 0"""
                    ).fetchall()
                    rdd_rate = list(rdd_rate) + list(rdd_total_heat)
                except sqlite3.OperationalError:
                    pass

            for rdd in rdd_rate:
                key = rdd["KeyValue"].upper()
                var_name = rdd["Name"].upper()
                idx = rdd["ReportDataDictionaryIndex"]
                matched = next((z for z in zones if key.startswith(z)), None)
                if matched is None:
                    continue
                avg_w = self._conn.execute(
                    "SELECT Value FROM ReportData WHERE ReportDataDictionaryIndex=? LIMIT 1",
                    (idx,),
                ).fetchone()
                if avg_w is None:
                    continue
                annual_kwh = float(avg_w[0]) * 8760.0 / 1000.0
                if "HEATING" in var_name:
                    zones[matched].heating_kwh += annual_kwh
                elif "COOLING" in var_name:
                    zones[matched].cooling_kwh += annual_kwh

        # ── Heating fallback: if all zones report zero heating, redistribute ────
        # building-total from AnnualBuildingUtilityPerformanceSummary by zone area.
        # Triggered when Output:Variable for Ideal Loads was absent in the original
        # IDF (e.g. projects already simulated before idf_parser injection was added).
        zone_list = list(zones.values())
        if sum(z.heating_kwh for z in zone_list) == 0.0:
            try:
                bldg_heating = self.parse_end_uses().heating_kwh
                total_area = sum(z.floor_area_m2 for z in zone_list if z.floor_area_m2 > 0)
                if bldg_heating > 0.0 and total_area > 0:
                    for z in zone_list:
                        z.heating_kwh = bldg_heating * (z.floor_area_m2 / total_area)
            except Exception:
                pass  # non-critical fallback

        # ── Compute totals ───────────────────────────────────────────────────────
        for z in zones.values():
            z.total_kwh = z.heating_kwh + z.cooling_kwh + z.lighting_kwh + z.equipment_kwh

        return list(zones.values())
