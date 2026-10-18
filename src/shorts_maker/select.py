"""Schritt 4: Die stärksten Abschnitte für Shorts auswählen.

Claude bekommt das Transkript mit nummerierten Segmenten und antwortet mit
Segment-ids. Weil Segmente an Satzgrenzen enden (siehe transcribe.resegment),
liegen die Schnittpunkte automatisch auf Satzgrenzen. `parse_selection`
validiert die Antwort und korrigiert Länge, Überlappungen und Grenzen.
"""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from . import llm
from .config import ClipConfig, Settings
from .errors import SelectionError
from .models import ClipCandidate, Segment, Transcript
from .transcribe import SENTENCE_END

log = logging.getLogger(__name__)

# Puffer an den Schnittkanten, damit kein Wort angeschnitten wird
LEAD_IN = 0.15
TAIL_OUT = 0.35


class ClipSuggestion(BaseModel):
    start_id: int
    end_id: int
    title: str
    hook: str
    reason: str
    score: float


class SelectionResponse(BaseModel):
    clips: list[ClipSuggestion]


SYSTEM = """Du bist ein erfahrener Social-Media-Editor und schneidest virale Short-Form-Clips
(YouTube Shorts, Instagram Reels, TikTok) aus langen Videos.

Ein guter Clip:
- hat einen starken Hook in den ersten 1–3 Sekunden (überraschende Aussage, Frage, Konflikt, Zahl),
- ist in sich abgeschlossen und ohne den Rest des Videos verständlich,
- endet mit einer Pointe, Erkenntnis oder einem klaren Abschluss – nicht mitten im Gedanken,
- enthält keine Begrüßungen, Sponsor-Hinweise oder "Abonniert den Kanal"-Passagen.

Du antwortest ausschließlich mit Segment-ids aus dem Transkript. start_id ist das erste,
end_id das letzte Segment des Clips (inklusive). Clips dürfen sich nicht überschneiden.
title (max. 60 Zeichen), hook und reason schreibst du auf Deutsch. score ist deine Einschätzung
des viralen Potenzials von 0 bis 100."""


def format_transcript(transcript: Transcript) -> str:
    return "\n".join(
        f"[{i}] {s.start:7.1f}-{s.end:7.1f} | {s.text}" for i, s in enumerate(transcript.segments)
    )


def build_prompt(transcript: Transcript, cfg: ClipConfig, n: int) -> str:
    return (
        f"Wähle die {n} stärksten Abschnitte für Shorts aus. Jeder Clip muss zwischen "
        f"{cfg.min_seconds:.0f} und {cfg.max_seconds:.0f} Sekunden lang sein "
        f"(Ende des letzten minus Start des ersten Segments). Sortiere nach score absteigend.\n\n"
        f"Sprache des Transkripts: {transcript.language}\n"
        f"Videolänge: {transcript.duration:.0f} s\n\n"
        f"Transkript (Format: [id] start-ende | Text):\n{format_transcript(transcript)}"
    )


def select_clips(transcript: Transcript, settings: Settings, client=None) -> list[ClipCandidate]:
    cfg = settings.clips
    # Etwas mehr anfragen, damit nach der Validierung genug übrig bleiben
    requested = cfg.count + max(1, math.ceil(cfg.count * 0.5))
    client = client or llm.make_client(settings)
    log.info("Lasse Claude die %d besten Clips auswählen …", cfg.count)
    response = llm.structured(
        client,
        model=settings.llm.model,
        system=SYSTEM,
        prompt=build_prompt(transcript, cfg, requested),
        schema=SelectionResponse,
        effort=settings.llm.select_effort,
    )
    return parse_selection(response, transcript, cfg)


# --------------------------------------------------------------------------- Parsing


def _coerce(raw: SelectionResponse | dict[str, Any] | list | str) -> list[ClipSuggestion]:
    """Akzeptiert das Pydantic-Objekt, ein dict/list oder einen JSON-String (ggf. mit ```-Fences)."""
    if isinstance(raw, SelectionResponse):
        return raw.clips
    if isinstance(raw, str):
        text = raw.strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SelectionError(f"Antwort ist kein gültiges JSON: {exc}") from exc
    if isinstance(raw, list):
        raw = {"clips": raw}
    try:
        return SelectionResponse.model_validate(raw).clips
    except ValidationError as exc:
        raise SelectionError(f"Antwort passt nicht zum erwarteten Schema: {exc}") from exc


def _ends_sentence(seg: Segment) -> bool:
    return seg.text.rstrip().rstrip("\"'»«“”)").endswith(SENTENCE_END)


def _span(segments: list[Segment], s: int, e: int) -> float:
    return segments[e].end - segments[s].start


def align_clip(segments: list[Segment], start: int, end: int, cfg: ClipConfig) -> tuple[int, int] | None:
    """Passt (start, end) an Satzgrenzen und an die erlaubte Länge an.

    Gibt None zurück, wenn sich kein gültiger Clip bilden lässt.
    """
    n = len(segments)
    if n == 0:
        return None
    start, end = max(0, min(start, n - 1)), max(0, min(end, n - 1))
    if start > end:
        start, end = end, start

    # Start auf Satzanfang ziehen: vorheriges Segment muss einen Satz beenden.
    for _ in range(3):
        if start == 0 or _ends_sentence(segments[start - 1]):
            break
        if _span(segments, start - 1, end) > cfg.max_seconds:
            break
        start -= 1

    # Ende auf Satzende schieben.
    for _ in range(4):
        if _ends_sentence(segments[end]) or end == n - 1:
            break
        if _span(segments, start, end + 1) > cfg.max_seconds:
            break
        end += 1

    # Zu kurz: nach hinten (bevorzugt bis Satzende), dann nach vorne erweitern.
    while _span(segments, start, end) < cfg.min_seconds:
        if end < n - 1 and _span(segments, start, end + 1) <= cfg.max_seconds:
            end += 1
        elif start > 0 and _span(segments, start - 1, end) <= cfg.max_seconds:
            start -= 1
        else:
            break
    while (
        end < n - 1
        and not _ends_sentence(segments[end])
        and _span(segments, start, end + 1) <= cfg.max_seconds
    ):
        end += 1

    # Zu lang: von hinten kürzen, bevorzugt auf ein Satzende.
    if _span(segments, start, end) > cfg.max_seconds:
        fitting = [e for e in range(start, end + 1) if _span(segments, start, e) <= cfg.max_seconds]
        if not fitting:
            return None
        sentence_ends = [e for e in fitting if _ends_sentence(segments[e]) and _span(segments, start, e) >= cfg.min_seconds]
        end = sentence_ends[-1] if sentence_ends else fitting[-1]

    duration = _span(segments, start, end)
    # Kleine Toleranz nach unten, z. B. wenn das Video selbst kürzer ist
    if duration < cfg.min_seconds * 0.8 or duration > cfg.max_seconds + 1e-6:
        return None
    return start, end


def _overlap(a: ClipCandidate, b: ClipCandidate) -> float:
    inter = min(a.end, b.end) - max(a.start, b.start)
    return max(0.0, inter) / max(1e-6, min(a.duration, b.duration))


def parse_selection(
    raw: SelectionResponse | dict[str, Any] | list | str,
    transcript: Transcript,
    cfg: ClipConfig,
    max_overlap: float = 0.2,
) -> list[ClipCandidate]:
    """Validiert die Modellantwort und erzeugt bis zu cfg.count Clips, nach score sortiert."""
    suggestions = _coerce(raw)
    segments = transcript.segments
    if not segments:
        raise SelectionError("Transkript ist leer.")

    candidates: list[ClipCandidate] = []
    for sug in sorted(suggestions, key=lambda s: s.score, reverse=True):
        if not (0 <= sug.start_id < len(segments)) or not (0 <= sug.end_id < len(segments)):
            log.warning("Verwerfe Clip '%s': Segment-id außerhalb des Transkripts.", sug.title)
            continue
        aligned = align_clip(segments, sug.start_id, sug.end_id, cfg)
        if aligned is None:
            log.warning("Verwerfe Clip '%s': Länge lässt sich nicht auf %g–%g s bringen.",
                        sug.title, cfg.min_seconds, cfg.max_seconds)
            continue
        s, e = aligned
        prev_end = segments[s - 1].end if s > 0 else 0.0
        next_start = segments[e + 1].start if e + 1 < len(segments) else transcript.duration
        clip = ClipCandidate(
            start=round(max(prev_end, segments[s].start - LEAD_IN, 0.0), 3),
            end=round(min(next_start, segments[e].end + TAIL_OUT, transcript.duration or segments[e].end + TAIL_OUT), 3),
            title=sug.title.strip()[:80] or f"Clip {len(candidates) + 1}",
            hook=sug.hook.strip(),
            reason=sug.reason.strip(),
            score=max(0.0, min(100.0, float(sug.score))),
        )
        if any(_overlap(clip, c) > max_overlap for c in candidates):
            log.info("Verwerfe Clip '%s': überschneidet sich mit einem besseren Clip.", clip.title)
            continue
        candidates.append(clip)
        if len(candidates) >= cfg.count:
            break

    if not candidates:
        raise SelectionError(
            "Es konnte kein gültiger Clip ausgewählt werden.",
            hint="Ist das Video lang genug? Passe ggf. --min-len/--max-len an.",
        )
    if len(candidates) < cfg.count:
        log.warning("Nur %d von %d gewünschten Clips gefunden.", len(candidates), cfg.count)
    return candidates


# --------------------------------------------------------------------------- Heuristik

_HOOK_PATTERN = re.compile(
    r"\?|!|\b(you|du|ihr|why|warum|how|wie|secret|geheim|never|nie|always|immer|mistake|fehler)\b|\d",
    re.IGNORECASE,
)


def heuristic_selection(transcript: Transcript, cfg: ClipConfig) -> SelectionResponse:
    """Offline-Fallback ohne API: bewertet Fenster nach Hook-Signalen und Sprechdichte."""
    segments = transcript.segments
    windows: list[ClipSuggestion] = []
    for s in range(len(segments)):
        if s > 0 and not _ends_sentence(segments[s - 1]):
            continue
        e = s
        while e + 1 < len(segments) and _span(segments, s, e + 1) <= cfg.max_seconds:
            e += 1
            if _span(segments, s, e) >= cfg.min_seconds and _ends_sentence(segments[e]):
                break
        if _span(segments, s, e) < cfg.min_seconds:
            continue
        hook = segments[s].text
        words = sum(len(seg.words) or len(seg.text.split()) for seg in segments[s : e + 1])
        density = words / max(1.0, _span(segments, s, e))
        score = 40 * min(1.0, density / 3.0) + 15 * len(_HOOK_PATTERN.findall(hook))
        windows.append(
            ClipSuggestion(
                start_id=s,
                end_id=e,
                title=hook[:60],
                hook=hook,
                reason=f"Heuristik: {density:.1f} Wörter/s, Hook-Signale im ersten Satz.",
                score=round(min(100.0, score), 1),
            )
        )
    return SelectionResponse(clips=windows)
