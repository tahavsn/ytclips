from ytclips.config import Settings
from ytclips.models import Segment, Transcript, Word
from ytclips.translate import TranslatedLine, TranslationBatch, distribute_words, translate

from .conftest import make_segment


def test_distribute_words_skips_pauses_and_keeps_bounds():
    seg = Segment(
        start=0.0,
        end=4.0,
        text="hello world",
        words=[Word(start=0.0, end=1.0, text="hello"), Word(start=3.0, end=4.0, text="world")],
    )
    words = distribute_words("Hallo schöne Welt", seg)
    assert [w.text for w in words] == ["Hallo", "schöne", "Welt"]
    assert words[0].start == 0.0 and words[-1].end == 4.0
    assert all(a.end <= b.start + 1e-6 for a, b in zip(words, words[1:]))
    # kein Wort beginnt mitten in der Pause (1.0 < t < 3.0)
    assert not any(1.0 < w.start < 3.0 for w in words)


def test_distribute_words_empty_text():
    seg = make_segment("hello there", 0)
    assert distribute_words("   ", seg) == []


class FakeLLM:
    """Ersetzt llm.structured: übersetzt per Wörterbuch, lässt beim 1. Mal eine Zeile weg."""

    def __init__(self):
        self.calls = 0

    def __call__(self, client, *, prompt, schema, **kwargs):
        self.calls += 1
        lines = []
        for row in prompt.splitlines():
            if row.startswith("["):
                idx, text = row[1:].split("] ", 1)
                if self.calls == 1 and idx == "1":
                    continue
                lines.append(TranslatedLine(id=int(idx), text="DE " + text))
        return TranslationBatch(lines=lines)


def test_translate_keeps_timestamps_and_retries_missing(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr("ytclips.translate.llm.structured", fake)
    t = Transcript(language="en", duration=10, segments=[make_segment("one two", 0), make_segment("three four", 2)])
    out = translate(t, Settings(), client=object())
    assert out.language == "de"
    assert [s.text for s in out.segments] == ["DE one two", "DE three four"]
    assert [(s.start, s.end) for s in out.segments] == [(s.start, s.end) for s in t.segments]
    assert fake.calls == 2


def test_translate_skips_same_language(monkeypatch):
    t = Transcript(language="de", duration=1, segments=[make_segment("hallo", 0)])
    assert translate(t, Settings(), client=object()) is t
