from __future__ import annotations

import os
import subprocess
import sys

import psycopg

from extract.extract import run as run_extract


def update_run(run_id, status: str, error: str | None = None) -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE pipeline_runs SET ended_at=now(), status=%s, error_message=%s WHERE run_id=%s",
            (status, error[:2000] if error else None, run_id),
        )


def main() -> None:
    run_id = run_extract()
    try:
        subprocess.run(["dbt", "run", "--project-dir", "dbt", "--profiles-dir", "dbt"], check=True)
        subprocess.run(["dbt", "test", "--project-dir", "dbt", "--profiles-dir", "dbt"], check=True)
    except Exception as exc:
        update_run(run_id, "failed", str(exc))
        raise
    update_run(run_id, "success")
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT object_counts FROM pipeline_runs WHERE run_id=%s", (run_id,))
        counts = cur.fetchone()[0]
        if counts and all(value == 0 for value in counts.values()):
            print(
                "WARNING: extractor returned zero rows for every object; "
                "investigate token, source activity, or watermark lag"
            )
            # An incremental run legitimately loads nothing when nothing
            # changed, so this is a warning by default. Where silence is always
            # wrong, FAIL_ON_EMPTY_RUN turns it into a failed build.
            if os.getenv("FAIL_ON_EMPTY_RUN", "").lower() in {"1", "true", "yes"}:
                sys.exit(1)


if __name__ == "__main__":
    main()
