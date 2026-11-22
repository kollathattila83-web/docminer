"""Feldolgozó: felveszi a sorból a következő iratot, és lefuttatja a hátralévő lépéseit.

Futtatás:  python -m docminer.worker          (folyamatosan)
           python -m docminer.worker --once   (egy kör, majd kilép)
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import time

from .db import Database
from .pipeline import run_document
from .queue import claim_next
from .settings import Settings, get_settings
from .storage import LocalStorage

log = logging.getLogger("docminer.worker")


def work_once(db: Database, storage: LocalStorage, settings: Settings, worker_id: str) -> str | None:
    doc_id = claim_next(db, worker_id)
    if doc_id is None:
        return None
    status = run_document(db, doc_id, storage, settings)
    log.info("Irat %s: %s", doc_id, status)
    return doc_id


def drain(db: Database, storage: LocalStorage, settings: Settings, worker_id: str = "inline") -> int:
    """Minden sorban álló irat feldolgozása (tesztekhez és parancssorhoz)."""
    n = 0
    while work_once(db, storage, settings, worker_id):
        n += 1
    return n


def main() -> None:
    parser = argparse.ArgumentParser(description="DocMiner feldolgozó")
    parser.add_argument("--once", action="store_true", help="a sor kiürítése után kilép")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    settings = get_settings()
    db = Database(settings.database_url)
    db.create_all()
    storage = LocalStorage(settings.data_dir)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    log.info("Feldolgozó indul: %s", worker_id)

    if args.once:
        drain(db, storage, settings, worker_id)
        return
    while True:
        try:
            if work_once(db, storage, settings, worker_id) is None:
                time.sleep(settings.worker_poll_seconds)
        except Exception:  # az adatbázis átmeneti hibája ne állítsa le a feldolgozót
            log.exception("Feldolgozói hiba, újrapróbálás")
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
