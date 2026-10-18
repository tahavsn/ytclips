"""Schritt 2: Transkription mit faster-whisper inkl. Wort-Zeitstempeln."""

from __future__ import annotations

import logging
from pathlib import Path

from .config import WhisperConfig
from .errors import DependencyError, TranscriptionError
from .models import Segment, Transcript, Word

log = logging.getLogger(__name__)

SENTENCE_END = (".", "!", "?", "…", "。", "！", "？")
CLAUSE_END = (",", ";", ":", "–", "—")


def _device_and_type(cfg: WhisperConfig) -> tuple[str, str]:
    device = cfg.device
    if device == "auto":
        try:
            import ctranslate2

            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:  # pragma: no cover - je nach Installation
            device = "cpu"
    compute = cfg.compute_type
    if compute == "auto":
        compute = "float16" if device == "cuda" else "int8"
    return device, compute


def transcribe(path: Path, cfg: WhisperConfig, language: str | None = None) -> Transcript:
    """Transkribiert die Audiospur; Sprache wird automatisch erkannt, wenn language=None."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover
        raise DependencyError("faster-whisper ist nicht installiert.", hint="pip install faster-whisper") from exc

    device, compute = _device_and_type(cfg)
    log.info("Lade Whisper-Modell '%s' (%s, %s) …", cfg.model, device, compute)
    try:
        model = WhisperModel(cfg.model, device=device, compute_type=compute)
    except Exception as exc:
        raise TranscriptionError(
            f"Whisper-Modell '{cfg.model}' konnte nicht geladen werden: {exc}",
            hint="Beim ersten Start wird das Modell von Hugging Face geladen (Internet nötig). "
            "Mit --whisper-model small geht es schneller.",
        ) from exc

    log.info("Transkribiere %s …", path.name)
    try:
        raw_segments, info = model.transcribe(
            str(path),
            language=language,
            word_timestamps=True,
            vad_filter=cfg.vad_filter,
            beam_size=cfg.beam_size,
        )
        segments = []
        for seg in raw_segments:
            words = [Word(start=w.start, end=w.end, text=w.word.strip()) for w in (seg.words or []) if w.word.strip()]
            segments.append(Segment(start=seg.start, end=seg.end, text=seg.text.strip(), words=words))
            log.debug("[%7.2f-%7.2f] %s", seg.start, seg.end, seg.text.strip())
    except Exception as exc:
        raise TranscriptionError(f"Transkription fehlgeschlagen: {exc}") from exc

    if not segments:
        raise TranscriptionError("Im Video wurde keine Sprache erkannt.")

    log.info("Erkannte Sprache: %s (p=%.2f), %d Segmente", info.language, info.language_probability, len(segments))
    transcript = Transcript(language=info.language, duration=info.duration, segments=segments)
    return resegment(transcript)


def resegment(transcript: Transcript, max_duration: float = 7.0, max_chars: int = 84, pause: float = 0.8) -> Transcript:
    """Teilt Whisper-Segmente an Satzgrenzen/Pausen in kurze, untertiteltaugliche Stücke.

    Kurze Segmente sind wichtig, weil (a) Clips an Segmentgrenzen geschnitten werden
    und (b) die Übersetzung pro Segment in ~2 Zeilen passen muss.
    """
    words = transcript.words()
    if not words:
        return transcript

    out: list[Segment] = []
    current: list[Word] = []

    def flush() -> None:
        if current:
            out.append(
                Segment(
                    start=current[0].start,
                    end=current[-1].end,
                    text=" ".join(w.text for w in current),
                    words=list(current),
                )
            )
            current.clear()

    for i, word in enumerate(words):
        if current:
            gap = word.start - current[-1].end
            length = sum(len(w.text) + 1 for w in current) + len(word.text)
            too_long = word.end - current[0].start > max_duration or length > max_chars
            if gap >= pause or too_long:
                flush()
        current.append(word)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if word.text.endswith(SENTENCE_END):
            flush()
        elif (
            word.text.endswith(CLAUSE_END)
            and nxt is not None
            and (word.end - current[0].start) > max_duration * 0.5
        ):
            flush()
    flush()
    return Transcript(language=transcript.language, duration=transcript.duration, segments=out)
