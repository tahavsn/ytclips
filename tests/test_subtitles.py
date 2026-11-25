import pytest

from ytclips.config import SubtitleConfig
from ytclips.models import Transcript
from ytclips.subtitles import (
    build_pages,
    clip_words,
    escape_text,
    format_time,
    hex_to_ass,
    render_ass,
)

from .conftest import make_segment, make_words


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, "0:00:00.00"), (1.234, "0:00:01.23"), (61.5, "0:01:01.50"), (3725.999, "1:02:06.00"), (-1, "0:00:00.00")],
)
def test_format_time(seconds, expected):
    assert format_time(seconds) == expected


def test_hex_to_ass_is_bgr_with_alpha():
    assert hex_to_ass("#FFE400") == "&H0000E4FF"
    assert hex_to_ass("#112233", alpha=0x80) == "&H80332211"


def test_escape_text_neutralises_override_tags():
    assert escape_text("{\\b1}hi") == "(/b1)hi"


def test_build_pages_respects_line_and_page_limits():
    words = make_words("das ist ein ziemlich langer Satz mit sehr vielen einzelnen Wörtern drin", step=0.3)
    pages = build_pages(words, max_chars=16, max_lines=2, pause_break=1.0)
    for page in pages:
        assert 1 <= len(page.lines) <= 2
        for line in page.lines:
            assert len(" ".join(w.text for w in line)) <= 16
    assert [w.text for p in pages for w in p.words] == [w.text for w in words]


def test_build_pages_breaks_on_sentence_end_and_pause():
    words = make_words("Hallo. Wie geht", step=0.3)
    words += make_words("es dir", start=words[-1].end + 2.0, step=0.3)
    pages = build_pages(words, max_chars=40, max_lines=2, pause_break=0.6)
    assert [[w.text for w in p.words] for p in pages] == [["Hallo."], ["Wie", "geht"], ["es", "dir"]]


def test_long_single_word_gets_own_line():
    words = make_words("Donaudampfschifffahrtsgesellschaft ist lang", step=0.3)
    pages = build_pages(words, max_chars=10, max_lines=2, pause_break=1.0)
    assert pages[0].lines[0][0].text.startswith("Donau")
    assert len(pages[0].lines[0]) == 1


def test_render_ass_has_one_event_per_word_with_highlight():
    cfg = SubtitleConfig(max_chars_per_line=20, max_lines=2, highlight_color="#FFE400", highlight_scale=100)
    words = make_words("eins zwei drei", step=0.5)
    ass = render_ass(words, cfg, 1080, 1920)
    events = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert len(events) == 3
    assert "{\\1c&H0000E4FF}eins{\\r} zwei drei" in events[0]
    assert "eins {\\1c&H0000E4FF}zwei{\\r} drei" in events[1]
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass


def test_render_ass_events_are_contiguous_and_end_after_last_word():
    cfg = SubtitleConfig()
    words = make_words("a b c d", step=0.5)
    events = [line.split(",") for line in render_ass(words, cfg).splitlines() if line.startswith("Dialogue:")]
    for prev, nxt in zip(events, events[1:]):
        assert prev[2] == nxt[1]  # Ende == Start des nächsten
    assert events[-1][2] >= format_time(words[-1].end)


def test_render_ass_multiline_uses_hard_breaks_and_uppercase():
    cfg = SubtitleConfig(max_chars_per_line=8, max_lines=2, uppercase=True)
    ass = render_ass(make_words("eins zwei drei vier"), cfg)
    first = next(line for line in ass.splitlines() if line.startswith("Dialogue:"))
    assert "\\N" in first
    assert "ZWEI" in first


def test_style_uses_config_values():
    cfg = SubtitleConfig(font="Montserrat", font_size=90, margin_v=500, outline=5)
    style = next(line for line in render_ass([], cfg).splitlines() if line.startswith("Style:"))
    assert style.startswith("Style: Default,Montserrat,90,")
    assert style.endswith(",500,1")
    assert ",5,2,2," in style  # Outline, Shadow, Alignment (unten mittig)


def test_clip_words_shifts_to_clip_start():
    t = Transcript(language="de", duration=30, segments=[make_segment("vor dem clip", 0), make_segment("im clip", 10)])
    words = clip_words(t, 9.5, 12.0)
    assert [w.text for w in words] == ["im", "clip"]
    assert words[0].start == pytest.approx(0.5)
