"""Aplica en orden los ficheros db/NNN_*.sql que aún no se hayan aplicado.

Uso:  DATABASE_URL=... python -m db.migrate
"""
import os
import pathlib

import psycopg

DIR = pathlib.Path(__file__).parent


def main() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("create table if not exists schema_migrations (name text primary key, applied_at timestamptz default now())")
        done = {r[0] for r in conn.execute("select name from schema_migrations")}
        for f in sorted(DIR.glob("[0-9][0-9][0-9]_*.sql")):
            if f.name in done:
                continue
            print("aplicando", f.name)
            with conn.transaction():
                conn.execute(f.read_text(encoding="utf-8"))
                conn.execute("insert into schema_migrations(name) values (%s)", (f.name,))
        print("migraciones al día")


if __name__ == "__main__":
    main()
