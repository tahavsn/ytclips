"""Einfacher JSON-Cache pro Video, damit Re-Runs Transkript & Übersetzung wiederverwenden."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)


def fingerprint(*parts: object) -> str:
    """Kurzer, stabiler Hash über beliebige (JSON-serialisierbare) Werte."""
    raw = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


class Cache:
    def __init__(self, root: Path, video_id: str, enabled: bool = True) -> None:
        self.dir = root / video_id
        self.enabled = enabled
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        return self.dir / name

    def load(self, name: str, model: type[M]) -> M | None:
        if not self.enabled:
            return None
        p = self.path(name)
        if not p.is_file():
            return None
        try:
            obj = model.model_validate_json(p.read_text(encoding="utf-8"))
        except (ValidationError, ValueError) as exc:
            log.warning("Cache-Datei %s ist beschädigt und wird ignoriert (%s)", p, exc)
            return None
        log.info("Cache-Treffer: %s", p)
        return obj

    def save(self, name: str, obj: BaseModel) -> Path:
        p = self.path(name)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(obj.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(p)
        return p
