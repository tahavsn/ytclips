from shorts_maker.models import Segment, Transcript
from shorts_maker.transcribe import resegment

from .conftest import make_words


def test_resegment_splits_at_sentence_end_and_pauses():
    words = make_words("Hallo zusammen. Heute geht es um Shorts", 0.0)
    words += make_words("nach einer langen Pause geht es weiter.", words[-1].end + 2.0)
    t = Transcript(
        language="de",
        duration=20,
        segments=[Segment(start=0, end=words[-1].end, text="x", words=words)],
    )
    out = resegment(t)
    texts = [s.text for s in out.segments]
    assert texts == [
        "Hallo zusammen.",
        "Heute geht es um Shorts",
        "nach einer langen Pause geht es weiter.",
    ]
    assert out.segments[1].end <= out.segments[2].start


def test_resegment_respects_max_chars():
    words = make_words(" ".join(["Wort"] * 60), 0.0, step=0.1)
    t = Transcript(language="de", duration=10, segments=[Segment(start=0, end=6, text="x", words=words)])
    out = resegment(t, max_chars=30)
    assert all(len(s.text) <= 30 for s in out.segments)
    assert sum(len(s.words) for s in out.segments) == 60
