"""Optional Apache Sedona overlay for explicitly synthetic commercial zones.

This isolated demonstration does not assert that its polygons represent official
land-use designations. It does not alter the store catchment publication path.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from geopulse.spatial import (
    DEFAULT_MAVEN_PACKAGES,
    SpatialJoinConfig,
    _child_path,
    _invalidate_batch_marker,
    _mark_batch_complete,
    _partition_matches_for_write,
    _require_spatial_dependencies,
    build_spark_session,
    ping_schema,
    prepare_pings,
)

AUDIT_METRICS = frozenset(
    {
        "raw_ping_rows",
        "valid_ping_rows",
        "rejected_ping_rows",
        "raw_zone_rows",
        "valid_zone_rows",
        "rejected_zone_rows",
        "matched_ping_zone_rows",
        "matched_unique_devices",
    }
)


@dataclass(frozen=True)
class ZoningOverlayConfig:
    pings_path: str
    zones_path: str
    output_path: str
    expected_ping_rows: int
    master: str = "local[2]"
    shuffle_partitions: int = 8
    maven_packages: str = DEFAULT_MAVEN_PACKAGES

    def __post_init__(self) -> None:
        for field_name in ("pings_path", "zones_path", "output_path", "master", "maven_packages"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.expected_ping_rows <= 0:
            raise ValueError("expected_ping_rows must be greater than zero")
        if self.shuffle_partitions <= 0:
            raise ValueError("shuffle_partitions must be greater than zero")


@dataclass(frozen=True)
class ZoningFrames:
    matches: Any
    zones: Any
    valid_pings: Any
    valid_zones: Any
    rejected_pings: Any
    rejected_zones: Any


def zone_schema() -> Any:
    """Read zone definitions without inferred geometry or provenance fields."""

    try:
        from pyspark.sql.types import StringType, StructField, StructType
    except ModuleNotFoundError as exc:
        raise RuntimeError("PySpark is required to build the zone schema") from exc
    return StructType(
        [
            StructField("zone_id", StringType(), True),
            StructField("zone_name", StringType(), True),
            StructField("zoning_class", StringType(), True),
            StructField("polygon_wkt", StringType(), True),
            StructField("source_label", StringType(), True),
        ]
    )


def prepare_zones(raw_zones: Any) -> tuple[Any, Any]:
    """Reject missing fields, non-synthetic sources, duplicates, and invalid polygons.

    A malformed WKT that Sedona cannot parse fails the job rather than becoming a
    silently accepted or dropped zone.
    """

    functions, _ = _require_spatial_dependencies()
    from pyspark.sql.window import Window

    def missing(name: str) -> Any:
        column = functions.col(name)
        return column.isNull() | (functions.length(functions.trim(column)) == 0)

    reason = (
        functions.when(missing("zone_id"), "missing_zone_id")
        .when(missing("zone_name"), "missing_zone_name")
        .when(missing("zoning_class"), "missing_zoning_class")
        .when(missing("polygon_wkt"), "missing_polygon_wkt")
        .when(functions.col("source_label") != "synthetic", "non_synthetic_zone_source")
        .when(functions.col("source_label").isNull(), "missing_source_label")
    )
    flagged = raw_zones.withColumn("rejection_reason", reason)
    invalid_fields = flagged.where(functions.col("rejection_reason").isNotNull())
    candidates = flagged.where(functions.col("rejection_reason").isNull()).drop("rejection_reason")
    window = Window.partitionBy("zone_id").orderBy(
        functions.col("zone_name"), functions.col("polygon_wkt")
    )
    ranked = candidates.withColumn("_duplicate_rank", functions.row_number().over(window))
    duplicates = (
        ranked.where(functions.col("_duplicate_rank") > 1)
        .drop("_duplicate_rank")
        .withColumn("rejection_reason", functions.lit("duplicate_zone_id"))
    )
    unique = ranked.where(functions.col("_duplicate_rank") == 1).drop("_duplicate_rank")
    parsed = unique.withColumn(
        "zone_geom", functions.expr("ST_SetSRID(ST_GeomFromWKT(polygon_wkt), 4326)")
    )
    polygon_type = functions.expr("ST_GeometryType(zone_geom)").isin(
        "ST_Polygon", "ST_MultiPolygon"
    )
    invalid_geometry = parsed.where(
        functions.col("zone_geom").isNull()
        | ~polygon_type
        | ~functions.expr("ST_IsValid(zone_geom)")
        | (functions.expr("ST_Area(zone_geom)") <= 0)
    )
    valid = parsed.where(
        functions.col("zone_geom").isNotNull()
        & polygon_type
        & functions.expr("ST_IsValid(zone_geom)")
        & (functions.expr("ST_Area(zone_geom)") > 0)
    )
    rejected_geometry = invalid_geometry.drop("zone_geom").withColumn(
        "rejection_reason", functions.lit("invalid_polygon")
    )
    rejected = invalid_fields.unionByName(duplicates).unionByName(rejected_geometry)
    return valid, rejected


def build_zoning_frames(raw_pings: Any, raw_zones: Any) -> ZoningFrames:
    """Match each valid WGS84 ping to every intersecting synthetic zone."""

    functions, _ = _require_spatial_dependencies()
    valid_pings, rejected_pings = prepare_pings(raw_pings)
    valid_zones, rejected_zones = prepare_zones(raw_zones)
    joined = valid_pings.alias("p").join(
        functions.broadcast(valid_zones.alias("z")),
        functions.expr("ST_Intersects(z.zone_geom, p.ping_geom)"),
        "inner",
    )
    matches = joined.select(
        functions.col("p.device_id").alias("device_id"),
        functions.col("p.event_ts").alias("event_ts"),
        functions.to_date("p.event_ts").alias("event_date"),
        functions.hour("p.event_ts").alias("event_hour_utc"),
        functions.col("p.latitude").alias("ping_latitude"),
        functions.col("p.longitude").alias("ping_longitude"),
        functions.col("z.zone_id").alias("zone_id"),
        functions.col("z.zone_name").alias("zone_name"),
        functions.col("z.zoning_class").alias("zoning_class"),
        functions.col("z.source_label").alias("source_label"),
    )
    zones = valid_zones.select(
        "zone_id",
        "zone_name",
        "zoning_class",
        "source_label",
        functions.expr("ST_AsText(zone_geom)").alias("polygon_wkt"),
    )
    return ZoningFrames(matches, zones, valid_pings, valid_zones, rejected_pings, rejected_zones)


def validate_zoning_metrics(metrics: Mapping[str, int], expected_ping_rows: int) -> None:
    """Fail closed on missing, rejected, or unreconciled synthetic observations."""

    missing = AUDIT_METRICS.difference(metrics)
    if missing:
        raise ValueError("Zone audit is missing: " + ", ".join(sorted(missing)))
    if expected_ping_rows <= 0:
        raise ValueError("expected_ping_rows must be greater than zero")
    for name in AUDIT_METRICS:
        value = metrics[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Zone audit {name} must be a non-negative integer")
    violations: list[str] = []
    if metrics["raw_ping_rows"] != expected_ping_rows:
        violations.append("raw ping count differs from expected")
    if metrics["raw_ping_rows"] != metrics["valid_ping_rows"] + metrics["rejected_ping_rows"]:
        violations.append("ping counts do not reconcile")
    if metrics["raw_zone_rows"] != metrics["valid_zone_rows"] + metrics["rejected_zone_rows"]:
        violations.append("zone counts do not reconcile")
    if metrics["rejected_ping_rows"] or metrics["rejected_zone_rows"]:
        violations.append("synthetic input contains rejected pings or zones")
    if metrics["valid_zone_rows"] == 0 or metrics["matched_ping_zone_rows"] == 0:
        violations.append("no valid zones or spatial matches")
    if not 0 < metrics["matched_unique_devices"] <= metrics["matched_ping_zone_rows"]:
        violations.append("matched device count is invalid")
    if metrics["matched_unique_devices"] > metrics["valid_ping_rows"]:
        violations.append("matched device count exceeds valid pings")
    if metrics["matched_ping_zone_rows"] > (
        metrics["valid_ping_rows"] * metrics["valid_zone_rows"]
    ):
        violations.append("match count exceeds point-zone combinations")
    if violations:
        raise ValueError("Zone quality gate failed: " + "; ".join(violations))


def run_zoning_overlay(config: ZoningOverlayConfig) -> dict[str, int | str]:
    """Write a standalone synthetic zone match batch with a completion marker."""

    spark = build_spark_session(
        SpatialJoinConfig(
            pings_path=config.pings_path,
            stores_path=config.zones_path,
            output_path=config.output_path,
            master=config.master,
            shuffle_partitions=config.shuffle_partitions,
            maven_packages=config.maven_packages,
        )
    )
    cached: list[Any] = []
    try:
        reader = spark.read.options(header=True, mode="PERMISSIVE")
        raw_pings = reader.schema(ping_schema()).csv(config.pings_path)
        raw_zones = reader.schema(zone_schema()).csv(config.zones_path)
        frames = build_zoning_frames(raw_pings, raw_zones)
        cached = [frames.valid_pings, frames.valid_zones, frames.matches]
        for frame in cached:
            frame.cache()
        metrics = {
            "raw_ping_rows": raw_pings.count(),
            "valid_ping_rows": frames.valid_pings.count(),
            "rejected_ping_rows": frames.rejected_pings.count(),
            "raw_zone_rows": raw_zones.count(),
            "valid_zone_rows": frames.valid_zones.count(),
            "rejected_zone_rows": frames.rejected_zones.count(),
            "matched_ping_zone_rows": frames.matches.count(),
            "matched_unique_devices": frames.matches.select("device_id").distinct().count(),
        }
        validate_zoning_metrics(metrics, config.expected_ping_rows)
        _invalidate_batch_marker(spark, config.output_path)
        (
            _partition_matches_for_write(frames.matches, config.shuffle_partitions)
            .write.mode("overwrite")
            .partitionBy("event_date", "event_hour_utc")
            .parquet(_child_path(config.output_path, "matches"))
        )
        frames.zones.coalesce(1).write.mode("overwrite").parquet(
            _child_path(config.output_path, "zones")
        )
        frames.rejected_pings.write.mode("overwrite").parquet(
            _child_path(config.output_path, "rejected_pings")
        )
        frames.rejected_zones.write.mode("overwrite").parquet(
            _child_path(config.output_path, "rejected_zones")
        )
        (
            spark.createDataFrame(list(metrics.items()), "metric string, value long")
            .withColumn("source_label", _require_spatial_dependencies()[0].lit("synthetic"))
            .coalesce(1)
            .write.mode("overwrite")
            .json(_child_path(config.output_path, "audit"))
        )
        _mark_batch_complete(spark, config.output_path)
        return {**metrics, "source_label": "synthetic", "output_path": config.output_path}
    finally:
        for frame in cached:
            frame.unpersist()
        spark.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Overlay synthetic pings on fictional commercial-zone polygons with Sedona."
    )
    parser.add_argument("--pings", required=True)
    parser.add_argument("--zones", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-ping-rows", required=True, type=int)
    parser.add_argument("--master", default="local[2]")
    parser.add_argument("--shuffle-partitions", type=int, default=8)
    parser.add_argument("--maven-packages", default=DEFAULT_MAVEN_PACKAGES)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = ZoningOverlayConfig(
        pings_path=args.pings,
        zones_path=args.zones,
        output_path=args.output,
        expected_ping_rows=args.expected_ping_rows,
        master=args.master,
        shuffle_partitions=args.shuffle_partitions,
        maven_packages=args.maven_packages,
    )
    print(json.dumps(run_zoning_overlay(config), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
