"""Opt-in export of an existing experiment to OCI; uses your normal SDK profile.

Never runs as a side effect of starting the lab. Do not pass credentials as CLI arguments.
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def export(args):
    import oci

    experiment = json.loads(Path(args.report).read_text())
    if "results" not in experiment or "id" not in experiment:
        raise ValueError("Expected an exported benchmark JSON")
    # Use a minimal allowlist so an arbitrary imported report cannot upload prompts.
    safe = {
        "id": experiment["id"],
        "created_at": experiment.get("created_at"),
        "results": [{"mode": r["mode"], "summary": r["summary"]} for r in experiment["results"]],
    }
    body = json.dumps(safe).encode()
    config = oci.config.from_file(profile_name=args.profile)
    if args.bucket:
        storage = oci.object_storage.ObjectStorageClient(config)
        namespace = storage.get_namespace().data
        storage.put_object(
            namespace,
            args.bucket,
            f"experiments/{experiment['id']}.json",
            body,
            content_type="application/json",
        )
        print("Uploaded aggregate report to private Object Storage bucket")
    if args.compartment:
        monitoring = oci.monitoring.MonitoringClient(
            config,
            service_endpoint=f"https://telemetry-ingestion.{config['region']}.oraclecloud.com",
        )
        metrics = []
        for result in safe["results"]:
            for name in [
                "ttft_p95_ms",
                "tpot_p95_ms",
                "output_tokens_per_second",
                "goodput_per_second",
            ]:
                value = result["summary"].get(name)
                if value is not None:
                    metrics.append(
                        oci.monitoring.models.MetricDataDetails(
                            namespace="llm_observatory",
                            compartment_id=args.compartment,
                            name=name,
                            dimensions={
                                "mode": result["mode"],
                                "source": "upstream"
                                if result["mode"] == "upstream"
                                else "simulated",
                            },
                            datapoints=[
                                oci.monitoring.models.Datapoint(
                                    timestamp=datetime.now(timezone.utc), value=value
                                )
                            ],
                        )
                    )
        if metrics:
            response = monitoring.post_metric_data(
                oci.monitoring.models.PostMetricDataDetails(metric_data=metrics)
            )
            if response.data.failed_metrics_count:
                raise RuntimeError("OCI rejected one or more metric datapoints")
            print("Exported aggregate metrics to OCI Monitoring")
    if args.adb:
        import oracledb

        kwargs = {
            "user": os.environ["ADB_USER"],
            "password": os.environ["ADB_PASSWORD"],
            "dsn": os.environ["ADB_DSN"],
        }
        if os.getenv("ADB_WALLET_DIR"):
            kwargs.update(
                config_dir=os.environ["ADB_WALLET_DIR"],
                wallet_location=os.environ["ADB_WALLET_DIR"],
                wallet_password=os.environ["ADB_WALLET_PASSWORD"],
            )
        with oracledb.connect(**kwargs) as connection:
            with connection.cursor() as cursor:
                try:
                    cursor.execute(
                        "CREATE TABLE lab_experiments (id VARCHAR2(64) PRIMARY KEY, payload CLOB CHECK (payload IS JSON))"
                    )
                except oracledb.DatabaseError as exc:
                    if exc.args[0].code != 955:
                        raise
                cursor.execute(
                    "MERGE INTO lab_experiments t USING (SELECT :id id, :payload payload FROM dual) s ON (t.id=s.id) WHEN MATCHED THEN UPDATE SET t.payload=s.payload WHEN NOT MATCHED THEN INSERT (id,payload) VALUES(s.id,s.payload)",
                    id=safe["id"],
                    payload=body.decode(),
                )
            connection.commit()
        print("Stored aggregate experiment in Autonomous Database")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("report")
    p.add_argument("--profile", default="DEFAULT")
    p.add_argument("--bucket")
    p.add_argument("--compartment")
    p.add_argument("--adb", action="store_true")
    args = p.parse_args()
    if not (args.bucket or args.compartment or args.adb):
        p.error("Select --bucket, --compartment, and/or --adb")
    export(args)
