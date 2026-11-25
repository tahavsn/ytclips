"""Schritt 3: Segmente per Claude übersetzen, Zeitstempel beibehalten."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from . import llm
from .config import Settings
from .models import Segment, Transcript, Word

log = logging.getLogger(__name__)

LANGUAGE_NAMES = {
    "de": "Deutsch",
    "en": "Englisch",
    "fr": "Französisch",
    "es": "Spanisch",
    "it": "Italienisch",
    "nl": "Niederländisch",
    "pt": "Portugiesisch",
    "tr": "Türkisch",
    "pl": "Polnisch",
}


class TranslatedLine(BaseModel):
    id: int
    text: str


class TranslationBatch(BaseModel):
    lines: list[TranslatedLine]


SYSTEM = """Du bist ein professioneller Untertitler für Short-Form-Videos (TikTok, Reels, Shorts).
Du übersetzt gesprochene Sprache in natürliche, gut lesbare Untertitel in der Zielsprache.

Regeln:
- Jede Zeile wird einzeln übersetzt und behält ihre id. Gib für jede id genau eine Zeile zurück,
  auch wenn die Zeile sehr kurz ist. Zeilen dürfen nicht zusammengelegt oder aufgeteilt werden.
- Untertitel sind kurz: höchstens {max_chars} Zeichen pro Zeile (das entspricht {lines} Zeilen
  à {per_line} Zeichen). Kürze sinnwahrend, wenn das Original länger ist; Füllwörter ("äh", "you know")
  fallen weg.
- Gesprochener, natürlicher Ton (du/ihr, wenn der Sprecher das Publikum direkt anspricht).
- Eigennamen, Marken und Zahlen bleiben korrekt erhalten.
- Der Kontext-Abschnitt dient nur dem Verständnis und wird nicht übersetzt."""


def needs_translation(transcript: Transcript, target: str) -> bool:
    return transcript.language.split("-")[0].lower() != target.split("-")[0].lower()


def distribute_words(text: str, source: Segment) -> list[Word]:
    """Verteilt die Wörter des übersetzten Texts auf die Sprechzeit des Originalsegments.

    Statt linear über das ganze Segment zu verteilen, werden die Sprechintervalle der
    Originalwörter als Zeitachse verwendet; so landen Wörter nicht in Pausen.
    Gewichtet wird nach Zeichenlänge (längere Wörter dauern länger).
    """
    tokens = text.split()
    if not tokens:
        return []
    intervals = [(w.start, w.end) for w in source.words if w.end > w.start] or [(source.start, source.end)]
    total = sum(e - s for s, e in intervals)
    if total <= 0:
        return [Word(start=source.start, end=source.end, text=t) for t in tokens]

    def time_at(fraction: float) -> float:
        remaining = fraction * total
        for s, e in intervals:
            if remaining <= e - s:
                return s + remaining
            remaining -= e - s
        return intervals[-1][1]

    weights = [len(t) + 1 for t in tokens]
    weight_sum = sum(weights)
    words: list[Word] = []
    acc = 0
    for token, weight in zip(tokens, weights):
        start = time_at(acc / weight_sum)
        acc += weight
        end = time_at(acc / weight_sum)
        words.append(Word(start=round(start, 3), end=round(end, 3), text=token))
    return words


def translate(transcript: Transcript, settings: Settings, client=None) -> Transcript:
    """Übersetzt alle Segmente in settings.target_language. Gibt ein neues Transkript zurück."""
    target = settings.target_language
    if not needs_translation(transcript, target):
        log.info("Quellsprache ist bereits %s – keine Übersetzung nötig.", target)
        return transcript

    client = client or llm.make_client(settings)
    tcfg = settings.translation
    max_chars = tcfg.max_chars_per_line * tcfg.max_lines
    system = SYSTEM.format(max_chars=max_chars, lines=tcfg.max_lines, per_line=tcfg.max_chars_per_line)
    src_name = LANGUAGE_NAMES.get(transcript.language, transcript.language)
    tgt_name = LANGUAGE_NAMES.get(target, target)

    segments = transcript.segments
    batch_size = settings.llm.translate_batch_size
    translated: dict[int, str] = {}

    for offset in range(0, len(segments), batch_size):
        batch = segments[offset : offset + batch_size]
        context = segments[max(0, offset - 3) : offset]
        log.info(
            "Übersetze Segmente %d–%d von %d (%s → %s) …",
            offset + 1, offset + len(batch), len(segments), src_name, tgt_name,
        )
        pending = {offset + i: s for i, s in enumerate(batch)}
        for attempt in range(2):
            # Beim zweiten Versuch werden nur noch die fehlenden ids angefragt.
            prompt = _build_prompt(src_name, tgt_name, pending, context)
            result = llm.structured(
                client,
                model=settings.llm.model,
                system=system,
                prompt=prompt,
                schema=TranslationBatch,
                effort=settings.llm.translate_effort,
            )
            for line in result.lines:
                if line.id in pending and line.text.strip():
                    translated[line.id] = line.text.strip()
            pending = {i: s for i, s in pending.items() if i not in translated}
            if not pending:
                break
            log.warning("%d Zeilen fehlen in der Antwort – frage erneut an (Versuch %d).", len(pending), attempt + 2)

        for i in pending:
            log.warning("Segment %d konnte nicht übersetzt werden; Originaltext wird verwendet.", i)
            translated[i] = segments[i].text

    out_segments = []
    for i, seg in enumerate(segments):
        text = translated[i]
        if len(text) > max_chars:
            log.debug("Segment %d ist mit %d Zeichen länger als %d.", i, len(text), max_chars)
        out_segments.append(Segment(start=seg.start, end=seg.end, text=text, words=distribute_words(text, seg)))
    return Transcript(language=target, duration=transcript.duration, segments=out_segments)


def _build_prompt(src_name: str, tgt_name: str, pending: dict[int, Segment], context: list[Segment]) -> str:
    lines = [f"Übersetze die folgenden Untertitelzeilen von {src_name} nach {tgt_name}.", ""]
    if context:
        lines.append("Kontext (nicht übersetzen):")
        lines.extend(f"  {s.text}" for s in context)
        lines.append("")
    lines.append("Zu übersetzende Zeilen (Format: [id] Text):")
    lines.extend(f"[{i}] {s.text}" for i, s in pending.items())
    return "\n".join(lines)
