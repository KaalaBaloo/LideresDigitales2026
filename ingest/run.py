"""CLI de ingesta.  python -m ingest.run [aforos censo agenda meteo parking] [--dry-run]

Sin argumentos ejecuta todos. Pensado para GitHub Actions (cron) contra Supabase.
"""
import argparse
import json
import logging
import sys

from .ckan import CKAN
from .connectors import CONNECTORS
from .store import Store


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("connectors", nargs="*", default=list(CONNECTORS))
    ap.add_argument("--dry-run", action="store_true", help="descarga y transforma sin escribir en BD")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ck, store = CKAN(), Store(dry_run=a.dry_run)
    failed = []
    for name in a.connectors:
        try:
            info = CONNECTORS[name](ck, store)
            print(name, json.dumps(info, default=str, ensure_ascii=False))
        except Exception:
            logging.exception("conector %s falló", name)
            failed.append(name)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
