"""Escritura en Postgres (Supabase) con procedencia y registro de ejecuciones."""
from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from typing import Iterable, Sequence

log = logging.getLogger(__name__)


class Store:
    """Si `dry_run` es True no toca la BD: solo cuenta filas (útil en CI y en local)."""

    def __init__(self, dsn: str | None = None, dry_run: bool = False):
        self.dry_run = dry_run
        self.conn = None
        if not dry_run:
            import psycopg

            self.conn = psycopg.connect(dsn or os.environ["DATABASE_URL"])

    @contextmanager
    def run(self, connector: str, dataset: str, resource: str | None):
        info = {"rows": 0, "detail": {}}
        run_id = None
        if self.conn:
            run_id = self.conn.execute(
                "insert into ingest_runs(connector, source_dataset, source_resource) values (%s,%s,%s) returning id",
                (connector, dataset, resource),
            ).fetchone()[0]
            self.conn.commit()
        try:
            yield info
            status = "ok"
        except Exception as e:
            status = "error"
            info["detail"]["error"] = repr(e)
            if self.conn:
                self.conn.rollback()
            raise
        finally:
            log.info("%s %s rows=%s status=%s", connector, resource, info["rows"], status)
            if self.conn:
                self.conn.execute(
                    "update ingest_runs set finished_at=now(), rows_loaded=%s, status=%s, detail=%s where id=%s",
                    (info["rows"], status, json.dumps(info["detail"], default=str), run_id),
                )
                self.conn.commit()

    def upsert(self, table: str, columns: Sequence[str], rows: Iterable[Sequence], conflict: Sequence[str]) -> int:
        """Carga masiva vía COPY a tabla temporal + INSERT ... ON CONFLICT DO UPDATE."""
        rows = list(rows)
        if self.dry_run or not rows:
            return len(rows)
        cols = ", ".join(columns)
        updates = ", ".join(f"{c}=excluded.{c}" for c in columns if c not in conflict) or None
        with self.conn.cursor() as cur:
            cur.execute(f"create temp table _stg (like {table} including defaults) on commit drop")
            with cur.copy(f"copy _stg ({cols}) from stdin") as cp:
                for r in rows:
                    cp.write_row(r)
            action = f"do update set {updates}, loaded_at=now()" if updates else "do nothing"
            cur.execute(
                f"insert into {table} ({cols}) select distinct on ({', '.join(conflict)}) {cols} from _stg "
                f"on conflict ({', '.join(conflict)}) {action}"
            )
        self.conn.commit()
        return len(rows)

    def execute(self, sql: str, params=None):
        if self.dry_run:
            return
        self.conn.execute(sql, params)
        self.conn.commit()
