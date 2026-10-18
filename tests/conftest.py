from __future__ import annotations

import pytest

from shorts_maker.models import Segment, Transcript, Word


def make_words(text: str, start: float = 0.0, step: float = 0.4) -> list[Word]:
    words = []
    t = start
    for token in text.split():
        words.append(Word(start=round(t, 3), end=round(t + step * 0.8, 3), text=token))
        t += step
    return words


def make_segment(text: str, start: float, step: float = 0.4) -> Segment:
    words = make_words(text, start, step)
    return Segment(start=words[0].start, end=words[-1].end, text=text, words=words)


@pytest.fixture
def transcript() -> Transcript:
    """~120 s Transkript aus Sätzen à 5 s mit Satzzeichen am Ende."""
    sentences = [
        "Did you know that most people get this completely wrong?",
        "Here is the thing nobody tells you about learning.",
        "You have to fail first, and you have to fail often.",
        "That is exactly what happened to me last year.",
        "I lost everything in just three weeks.",
        "But then something changed in my head.",
        "I started to track every single mistake.",
        "And after a month the pattern was obvious.",
        "So here is my advice for you today.",
        "Write it down, every single day, no excuses.",
        "Now let us talk about something different.",
        "The weather was nice and we went outside.",
    ] * 2
    segments = [make_segment(s, i * 5.0) for i, s in enumerate(sentences)]
    return Transcript(language="en", duration=len(sentences) * 5.0, segments=segments)
