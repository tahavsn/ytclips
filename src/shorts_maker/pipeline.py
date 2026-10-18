"""Orchestriert alle Schritte und schreibt Clips + clips.json."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from . import crop, download, export, select, subtitles, transcribe, translate
from .cache import Cache, fingerprint
from .config import Settings
from .models import ClipCandidate, ClipResult, Transcript

log = logging.getLogger(__name__)


class Selection(BaseModel):
    clips: list[ClipCandidate]


UMLAUTS = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}


def slugify(text: str, max_len: int = 40) -> str:
    for src, dst in UMLAUTS.items():
        text = text.replace(src, dst)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].rstrip("-") or "clip"


def run(
    source: str,
    settings: Settings,
    output_dir: Path,
    *,
    use_cache: bool = True,
    translate_enabled: bool = True,
    selector: str = "claude",
    source_language: str | None = None,
) -> Path:
    """Führt die komplette Pipeline aus und gibt den Pfad zu clips.json zurück."""
    # 1. Download / lokale Datei
    video = download.get_source(source, settings.cache_dir, settings.download)
    cache = Cache(settings.cache_dir, video.id, enabled=use_cache)
    info = download.probe(video.path)
    log.info("Quelle: %s (%dx%d, %.0f s)", video.title, info["width"], info["height"], info["duration"])

    # 2. Transkription
    t_name = f"transcript_{fingerprint(settings.whisper.model, source_language)}.json"
    transcript = cache.load(t_name, Transcript)
    if transcript is None:
        transcript = transcribe.transcribe(video.path, settings.whisper, language=source_language)
        cache.save(t_name, transcript)

    # 3. Übersetzung
    subtitle_transcript = transcript
    if translate_enabled and translate.needs_translation(transcript, settings.target_language):
        tr_name = (
            f"translation_{settings.target_language}_"
            f"{fingerprint(transcript.model_dump(), settings.llm.model, settings.translation.model_dump())}.json"
        )
        subtitle_transcript = cache.load(tr_name, Transcript)
        if subtitle_transcript is None:
            subtitle_transcript = translate.translate(transcript, settings)
            cache.save(tr_name, subtitle_transcript)
    elif not translate_enabled:
        log.info("Übersetzung deaktiviert – Untertitel in Originalsprache (%s).", transcript.language)

    # 4. Clip-Auswahl (auf dem Original-Transkript, das ist präziser)
    s_name = f"selection_{selector}_{fingerprint(transcript.model_dump(), settings.clips.model_dump(), settings.llm.model)}.json"
    cached_sel = cache.load(s_name, Selection)
    if cached_sel is not None:
        clips = cached_sel.clips
    else:
        if selector == "heuristic":
            log.info("Wähle Clips per Heuristik (offline).")
            clips = select.parse_selection(select.heuristic_selection(transcript, settings.clips), transcript, settings.clips)
        else:
            clips = select.select_clips(transcript, settings)
        cache.save(s_name, Selection(clips=clips))

    # 5–7. Crop, Untertitel, Export
    out_dir = output_dir / video.id
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[ClipResult] = []
    for i, clip in enumerate(clips, start=1):
        stem = f"clip_{i:02d}_{slugify(clip.title)}"
        log.info("[%d/%d] %s (%.1f–%.1f s, %.0f s)", i, len(clips), clip.title, clip.start, clip.end, clip.duration)

        plan = crop.plan_crop(video.path, clip.start, clip.end, info["width"], info["height"], settings.crop,
                              settings.cache_dir)
        words = subtitles.clip_words(subtitle_transcript, clip.start, clip.end)
        ass_path = subtitles.write_ass(out_dir / f"{stem}.ass", words, settings.subtitles,
                                       settings.export.width, settings.export.height, clip.duration)
        mp4 = export.render_clip(video.path, out_dir / f"{stem}.mp4", clip.start, clip.end, plan, ass_path,
                                 settings.export, settings.subtitles, info["has_audio"])
        results.append(
            ClipResult(
                index=i,
                file=mp4.name,
                start=clip.start,
                end=clip.end,
                duration=round(clip.duration, 3),
                title=clip.title,
                hook=clip.hook,
                reason=clip.reason,
                score=clip.score,
                subtitle_file=ass_path.name,
                crop_mode=plan.mode,
            )
        )
        log.info("  → %s (Crop: %s)", mp4, plan.mode)

    meta = {
        "source": {"id": video.id, "title": video.title, "url": video.url, "path": str(video.path),
                   "duration": info["duration"]},
        "source_language": transcript.language,
        "subtitle_language": subtitle_transcript.language,
        "selector": selector,
        "model": settings.llm.model if selector == "claude" else None,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "clips": [r.model_dump() for r in results],
    }
    meta_path = out_dir / "clips.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta_path
