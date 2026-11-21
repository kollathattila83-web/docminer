"""Fájltárolás. Helyben mappa; később S3-kompatibilis tárhelyre cserélhető ugyanezzel a felülettel.

Az adatbázisba csak a tárolón belüli relatív kulcs kerül, így a tároló áthelyezhető.

Mappaszerkezet iratonként (ez egyben az AI-ready csomag):
    documents/<id>/original/<fájlnév>      az eredeti fájl, érintetlenül
    documents/<id>/pages/page-0001.png     oldalkép
    documents/<id>/text/page-0001.txt      oldal szövege
    documents/<id>/text/page-0001.json     szavak, blokkok, táblák koordinátákkal
    documents/<id>/manifest.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def safe_filename(name: str) -> str:
    name = Path(name or "").name  # útvonal-részek eldobása
    name = re.sub(r"[^\w.\- ]", "_", name, flags=re.UNICODE).strip(" .")
    return name[:200] or "upload"


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise ValueError(f"Érvénytelen tárolókulcs: {key}")
        return p

    def put_bytes(self, key: str, data: bytes) -> str:
        p = self.path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)  # atomi csere: félbehagyott írás nem marad
        return key

    def put_text(self, key: str, text: str) -> str:
        return self.put_bytes(key, text.encode("utf-8"))

    def put_json(self, key: str, obj) -> str:
        return self.put_text(key, json.dumps(obj, ensure_ascii=False, indent=2))

    def get_bytes(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self.path(key).exists()

    # Kulcsok egy helyen, hogy minden modul ugyanazt használja.
    @staticmethod
    def doc_prefix(doc_id: str) -> str:
        return f"documents/{doc_id}"

    @classmethod
    def original_key(cls, doc_id: str, filename: str) -> str:
        return f"{cls.doc_prefix(doc_id)}/original/{safe_filename(filename)}"

    @classmethod
    def page_image_key(cls, doc_id: str, number: int) -> str:
        return f"{cls.doc_prefix(doc_id)}/pages/page-{number:04d}.png"

    @classmethod
    def page_text_key(cls, doc_id: str, number: int) -> str:
        return f"{cls.doc_prefix(doc_id)}/text/page-{number:04d}.txt"

    @classmethod
    def page_layout_key(cls, doc_id: str, number: int) -> str:
        return f"{cls.doc_prefix(doc_id)}/text/page-{number:04d}.json"

    @classmethod
    def manifest_key(cls, doc_id: str) -> str:
        return f"{cls.doc_prefix(doc_id)}/manifest.json"
