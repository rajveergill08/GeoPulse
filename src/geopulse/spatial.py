"""Apache Sedona pipeline for matching mobility pings to store catchments.

The module keeps PySpark and Sedona as optional imports so the lightweight
synthetic-data tooling remains usable without a local Spark installation.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

SEDONA_VERSION = "1.9.0"
SPARK_VERSION = "4.0.4"
SCALA_BINARY_VERSION = "2.13"
GEOTOOLS_WRAPPER_VERSION = "1.9.0-33.5"
SEDONA_SPARK_MAVEN_PACKAGE = (
    f"org.apache.sedona:sedona-spark-shaded-4.0_{SCALA_BINARY_VERSION}:{SEDONA_VERSION}"
)
GEOTOOLS_MAVEN_PACKAGE = f"org.datasyslab:geotools-wrapper:{GEOTOOLS_WRAPPER_VERSION}"
DEFAULT_MAVEN_PACKAGES = f"{SEDONA_SPARK_MAVEN_PACKAGE},{GEOTOOLS_MAVEN_PACKAGE}"

WRITE_MODES = frozenset({"append", "error", "errorifexists", "ignore", "overwrite"})


@dataclass(frozen=True)
class SpatialJoinConfig:
    """Runtime configuration for a catchment join."""

    pings_path: str
    stores_path: str
    output_path: str
    master: str = "local[*]"
    shuffle_partitions: int = 200
    write_mode: str = "overwrite"
    maven_packages: str = DEFAULT_MAVEN_PACKAGES

    def __post_init__(self) -> None:
        for field_name in ("pings_path", "stores_path", "output_path", "master"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.shuffle_partitions <= 0:
            raise ValueError("shuffle_partitions must be greater than zero")
        if self.write_mode.lower() not in WRITE_MODES:
            allowed = ", ".join(sorted(WRITE_MODES))
            raise ValueError(f"write_mode must be one of: {allowed}")
        if not self.maven_packages.strip():
            raise ValueError("maven_packages must not be empty")


@dataclass(frozen=True)
class SpatialFrames:
    """Validated outputs produced before persistence."""

    matches: Any
    catchments: Any
    valid_pings: Any
    valid_stores: Any
    rejected_pings: Any
    rejected_stores: Any


def _require_spatial_dependencies() -> tuple[Any, Any]:
    try:
        from pyspark.sql import functions as spark_functions
        from sedona.spark import SedonaContext
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Spatial dependencies are missing or incomplete. Run "
            "`python -m pip install --editable '.[spatial]'`."
        ) from exc
    return spark_functions, SedonaContext


def build_spark_session(config: SpatialJoinConfig) -> Any:
    """Create a UTC Spark session with Sedona SQL functions registered."""

    _, sedona_context = _require_spatial_dependencies()
    spark = (
        sedona_context.builder()
        .master(config.master)
        .appName("GeoPulse Spatial Catchment Join")
        .config("spark.jars.packages", config.maven_packages)
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", str(config.shuffle_partitions))
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    return sedona_context.create(spark)


def ping_schema() -> Any:
    """Return the explicit schema for synthetic mobility CSV files."""

    try:
        from pyspark.sql.types import DoubleType, StringType, StructField, StructType
    except ModuleNotFoundError as exc:
        raise RuntimeError("PySpark is required to build the ping schema") from exc

    return StructType(
        [
            StructField("device_id", StringType(), True),
            StructField("event_ts", StringType(), True),
            StructField("latitude", DoubleType(), True),
            StructField("longitude", DoubleType(), True),
            StructField("accuracy_m", DoubleType(), True),
            StructField("activity_type", StringType(), True),
        ]
    )


def store_schema() -> Any:
    """Return the explicit schema for store catchment definitions."""

    try:
        from pyspark.sql.types import DoubleType, StringType, StructField, StructType
    except ModuleNotFoundError as exc:
        raise RuntimeError("PySpark is required to build the store schema") from exc

    return StructType(
        [
            StructField("store_id", StringType(), True),
            StructField("store_name", StringType(), True),
            StructField("status", StringType(), True),
            StructField("latitude", DoubleType(), True),
            StructField("longitude", DoubleType(), True),
            StructField("catchment_radius_m", DoubleType(), True),
        ]
    )


def read_inputs(spark: Any, config: SpatialJoinConfig) -> tuple[Any, Any]:
    """Read mobility and store CSV inputs without schema inference."""

    reader = spark.read.options(header=True, mode="PERMISSIVE")
    pings = reader.schema(ping_schema()).csv(config.pings_path)
    stores = reader.schema(store_schema()).csv(config.stores_path)
    return pings, stores


def _empty_or_null(column: Any, functions: Any) -> Any:
    return column.isNull() | (functions.length(functions.trim(column)) == 0)


def prepare_pings(raw_pings: Any) -> tuple[Any, Any]:
    """Validate, deduplicate, and create WGS84 point geometries for pings."""

    functions, _ = _require_spatial_dependencies()
    from pyspark.sql.window import Window

    parsed = raw_pings.withColumnRenamed("event_ts", "event_ts_raw").withColumn(
        "event_ts", functions.expr("try_cast(event_ts_raw as timestamp)")
    )
    invalid_reason = (
        functions.when(_empty_or_null(functions.col("device_id"), functions), "missing_device_id")
        .when(functions.col("event_ts").isNull(), "invalid_event_timestamp")
        .when(
            functions.col("latitude").isNull() | ~functions.col("latitude").between(-90.0, 90.0),
            "invalid_latitude",
        )
        .when(
            functions.col("longitude").isNull()
            | ~functions.col("longitude").between(-180.0, 180.0),
            "invalid_longitude",
        )
        .when(
            functions.col("accuracy_m").isNotNull() & (functions.col("accuracy_m") < 0.0),
            "invalid_accuracy",
        )
    )
    flagged = parsed.withColumn("rejection_reason", invalid_reason)
    invalid = flagged.where(functions.col("rejection_reason").isNotNull())
    candidates = flagged.where(functions.col("rejection_reason").isNull()).drop("rejection_reason")

    duplicate_window = Window.partitionBy("device_id", "event_ts").orderBy(
        functions.col("latitude"),
        functions.col("longitude"),
        functions.col("accuracy_m").asc_nulls_last(),
        functions.col("activity_type").asc_nulls_last(),
    )
    ranked = candidates.withColumn("_duplicate_rank", functions.row_number().over(duplicate_window))
    duplicates = (
        ranked.where(functions.col("_duplicate_rank") > 1)
        .drop("_duplicate_rank")
        .withColumn("rejection_reason", functions.lit("duplicate_device_timestamp"))
    )
    valid = (
        ranked.where(functions.col("_duplicate_rank") == 1)
        .drop("_duplicate_rank")
        .withColumn(
            "ping_geom",
            functions.expr("ST_SetSRID(ST_Point(longitude, latitude), 4326)"),
        )
    )
    rejected = invalid.unionByName(duplicates)
    return valid, rejected


def prepare_stores(raw_stores: Any) -> tuple[Any, Any]:
    """Validate stores and create metric catchment polygons."""

    functions, _ = _require_spatial_dependencies()
    from pyspark.sql.window import Window

    invalid_reason = (
        functions.when(_empty_or_null(functions.col("store_id"), functions), "missing_store_id")
        .when(_empty_or_null(functions.col("store_name"), functions), "missing_store_name")
        .when(_empty_or_null(functions.col("status"), functions), "missing_status")
        .when(
            functions.col("latitude").isNull() | ~functions.col("latitude").between(-90.0, 90.0),
            "invalid_latitude",
        )
        .when(
            functions.col("longitude").isNull()
            | ~functions.col("longitude").between(-180.0, 180.0),
            "invalid_longitude",
        )
        .when(
            functions.col("catchment_radius_m").isNull()
            | ~functions.col("catchment_radius_m").between(1.0, 10_000.0),
            "invalid_catchment_radius",
        )
    )
    flagged = raw_stores.withColumn("rejection_reason", invalid_reason)
    invalid = flagged.where(functions.col("rejection_reason").isNotNull())
    candidates = flagged.where(functions.col("rejection_reason").isNull()).drop("rejection_reason")

    duplicate_window = Window.partitionBy("store_id").orderBy(
        functions.col("store_name"),
        functions.col("latitude"),
        functions.col("longitude"),
    )
    ranked = candidates.withColumn("_duplicate_rank", functions.row_number().over(duplicate_window))
    duplicates = (
        ranked.where(functions.col("_duplicate_rank") > 1)
        .drop("_duplicate_rank")
        .withColumn("rejection_reason", functions.lit("duplicate_store_id"))
    )
    valid = (
        ranked.where(functions.col("_duplicate_rank") == 1)
        .drop("_duplicate_rank")
        .withColumn(
            "store_geom",
            functions.expr("ST_SetSRID(ST_Point(longitude, latitude), 4326)"),
        )
        .withColumn(
            "catchment_geom",
            functions.expr("ST_Buffer(store_geom, catchment_radius_m, true)"),
        )
    )
    rejected = invalid.unionByName(duplicates)
    return valid, rejected


def build_spatial_frames(raw_pings: Any, raw_stores: Any) -> SpatialFrames:
    """Build validated catchments and point-in-polygon matches."""

    functions, _ = _require_spatial_dependencies()
    valid_pings, rejected_pings = prepare_pings(raw_pings)
    valid_stores, rejected_stores = prepare_stores(raw_stores)

    pings = valid_pings.alias("p")
    catchments = valid_stores.alias("s")
    joined = pings.join(
        functions.broadcast(catchments),
        functions.expr("ST_Intersects(s.catchment_geom, p.ping_geom)"),
        "inner",
    )
    matches = joined.select(
        functions.col("p.device_id").alias("device_id"),
        functions.col("p.event_ts").alias("event_ts"),
        functions.to_date("p.event_ts").alias("event_date"),
        functions.hour("p.event_ts").alias("event_hour_utc"),
        functions.col("p.latitude").alias("ping_latitude"),
        functions.col("p.longitude").alias("ping_longitude"),
        functions.col("p.accuracy_m").alias("accuracy_m"),
        functions.col("p.activity_type").alias("activity_type"),
        functions.col("s.store_id").alias("store_id"),
        functions.col("s.store_name").alias("store_name"),
        functions.col("s.status").alias("store_status"),
        functions.col("s.catchment_radius_m").alias("catchment_radius_m"),
        functions.expr("ST_DistanceSphere(p.ping_geom, s.store_geom)").alias("distance_to_store_m"),
    )
    catchment_output = valid_stores.select(
        "store_id",
        "store_name",
        "status",
        "latitude",
        "longitude",
        "catchment_radius_m",
        functions.expr("ST_AsText(catchment_geom)").alias("catchment_wkt"),
    )
    return SpatialFrames(
        matches=matches,
        catchments=catchment_output,
        valid_pings=valid_pings,
        valid_stores=valid_stores,
        rejected_pings=rejected_pings,
        rejected_stores=rejected_stores,
    )


def _child_path(base_path: str, child: str) -> str:
    normalized = base_path.replace("\\", "/").rstrip("/")
    return f"{normalized}/{child}"


def _write_outputs(
    spark: Any,
    config: SpatialJoinConfig,
    frames: SpatialFrames,
    audit_metrics: list[tuple[str, int]],
) -> None:
    functions, _ = _require_spatial_dependencies()
    mode = config.write_mode.lower()
    (
        frames.matches.repartition("event_date")
        .write.mode(mode)
        .partitionBy("event_date", "event_hour_utc")
        .parquet(_child_path(config.output_path, "matches"))
    )
    frames.catchments.coalesce(1).write.mode(mode).parquet(
        _child_path(config.output_path, "catchments")
    )
    frames.rejected_pings.write.mode(mode).parquet(
        _child_path(config.output_path, "rejected_pings")
    )
    frames.rejected_stores.write.mode(mode).parquet(
        _child_path(config.output_path, "rejected_stores")
    )
    (
        spark.createDataFrame(audit_metrics, "metric string, value long")
        .withColumn("recorded_at_utc", functions.current_timestamp())
        .coalesce(1)
        .write.mode(mode)
        .json(_child_path(config.output_path, "audit"))
    )


def run_spatial_join(config: SpatialJoinConfig) -> dict[str, int | str]:
    """Execute the full spatial join and return its audit summary."""

    spark = build_spark_session(config)
    cached_frames: list[Any] = []
    try:
        raw_pings, raw_stores = read_inputs(spark, config)
        frames = build_spatial_frames(raw_pings, raw_stores)

        # Cache only reusable validated data and match results. Keeping raw and
        # rejected inputs out of cache avoids holding multiple full copies of a
        # multi-million-row ping dataset in executor memory.
        cached_frames = [frames.valid_pings, frames.valid_stores, frames.matches]
        for frame in cached_frames:
            frame.cache()

        metrics = {
            "raw_ping_rows": raw_pings.count(),
            "valid_ping_rows": frames.valid_pings.count(),
            "rejected_ping_rows": frames.rejected_pings.count(),
            "raw_store_rows": raw_stores.count(),
            "valid_store_rows": frames.valid_stores.count(),
            "rejected_store_rows": frames.rejected_stores.count(),
            "matched_ping_store_rows": frames.matches.count(),
            "matched_unique_devices": frames.matches.select("device_id").distinct().count(),
        }
        _write_outputs(spark, config, frames, list(metrics.items()))
        return {
            **metrics,
            "output_path": config.output_path,
            "maven_packages": config.maven_packages,
        }
    finally:
        for frame in cached_frames:
            frame.unpersist()
        spark.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Match mobility pings to metric store catchments with Apache Sedona."
    )
    parser.add_argument("--pings", required=True, help="CSV/CSV.GZ path or Spark path glob")
    parser.add_argument("--stores", required=True, help="Store CSV path or Spark path glob")
    parser.add_argument("--output", required=True, help="Base path for Parquet and audit outputs")
    parser.add_argument("--master", default="local[*]", help="Spark master URL")
    parser.add_argument("--shuffle-partitions", type=int, default=200)
    parser.add_argument("--write-mode", choices=sorted(WRITE_MODES), default="overwrite")
    parser.add_argument(
        "--maven-packages",
        default=DEFAULT_MAVEN_PACKAGES,
        help="Comma-separated Sedona and GeoTools Maven coordinates",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = SpatialJoinConfig(
            pings_path=args.pings,
            stores_path=args.stores,
            output_path=args.output,
            master=args.master,
            shuffle_partitions=args.shuffle_partitions,
            write_mode=args.write_mode,
            maven_packages=args.maven_packages,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(run_spatial_join(config), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
