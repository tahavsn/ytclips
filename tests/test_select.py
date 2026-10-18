import json

import pytest

from shorts_maker.config import ClipConfig
from shorts_maker.errors import SelectionError
from shorts_maker.select import (
    SelectionResponse,
    align_clip,
    build_prompt,
    heuristic_selection,
    parse_selection,
)

from .conftest import make_segment

CFG = ClipConfig(count=3, min_seconds=30, max_seconds=60)


def suggestion(start_id, end_id, score=80, title="Titel"):
    return {
        "start_id": start_id,
        "end_id": end_id,
        "title": title,
        "hook": "Hook",
        "reason": "Weil",
        "score": score,
    }


def test_parse_valid_json_string(transcript):
    raw = json.dumps({"clips": [suggestion(0, 7, 90, "A"), suggestion(12, 19, 70, "B")]})
    clips = parse_selection(raw, transcript, CFG)
    assert [c.title for c in clips] == ["A", "B"]
    for c in clips:
        assert CFG.min_seconds <= c.duration <= CFG.max_seconds + 1


def test_parse_accepts_code_fence_and_bare_list(transcript):
    raw = "Hier:\n```json\n" + json.dumps([suggestion(0, 7)]) + "\n```"
    clips = parse_selection(raw, transcript, CFG)
    assert len(clips) == 1


def test_parse_accepts_pydantic_object(transcript):
    obj = SelectionResponse.model_validate({"clips": [suggestion(0, 7)]})
    assert len(parse_selection(obj, transcript, CFG)) == 1


def test_parse_rejects_invalid_json(transcript):
    with pytest.raises(SelectionError):
        parse_selection("{not json", transcript, CFG)


def test_parse_rejects_schema_mismatch(transcript):
    with pytest.raises(SelectionError):
        parse_selection({"clips": [{"start_id": 0}]}, transcript, CFG)


def test_parse_drops_out_of_range_ids(transcript):
    raw = {"clips": [suggestion(500, 510, 99), suggestion(0, 7, 50, "ok")]}
    clips = parse_selection(raw, transcript, CFG)
    assert [c.title for c in clips] == ["ok"]


def test_parse_sorts_by_score_and_limits_count(transcript):
    raw = {"clips": [suggestion(0, 7, 10, "low"), suggestion(8, 15, 95, "top"),
                     suggestion(16, 23, 50, "mid"), suggestion(12, 19, 40, "overlap")]}
    clips = parse_selection(raw, transcript, ClipConfig(count=2, min_seconds=30, max_seconds=60))
    assert [c.title for c in clips] == ["top", "mid"]


def test_parse_removes_overlaps(transcript):
    raw = {"clips": [suggestion(0, 7, 90, "first"), suggestion(1, 8, 80, "dup")]}
    clips = parse_selection(raw, transcript, CFG)
    assert [c.title for c in clips] == ["first"]


def test_too_short_suggestion_is_extended(transcript):
    clips = parse_selection({"clips": [suggestion(2, 3)]}, transcript, CFG)
    assert clips[0].duration >= CFG.min_seconds


def test_too_long_suggestion_is_trimmed(transcript):
    clips = parse_selection({"clips": [suggestion(0, 20)]}, transcript, CFG)
    assert clips[0].duration <= CFG.max_seconds + 0.5


def test_swapped_ids_are_fixed(transcript):
    clips = parse_selection({"clips": [suggestion(7, 0)]}, transcript, CFG)
    assert clips[0].start < clips[0].end


def test_score_is_clamped(transcript):
    clips = parse_selection({"clips": [suggestion(0, 7, 250)]}, transcript, CFG)
    assert clips[0].score == 100


def test_no_valid_clip_raises(transcript):
    with pytest.raises(SelectionError):
        parse_selection({"clips": []}, transcript, CFG)


def test_cuts_land_on_sentence_boundaries():
    # Satz über zwei Segmente: Segment 1 endet ohne Punkt.
    texts = ["Erster Satz geht hier", "noch weiter bis hier.", "Zweiter Satz ist kurz.",
             "Dritter Satz beginnt", "und endet hier."]
    segs = [make_segment(t, i * 8.0, step=1.5) for i, t in enumerate(texts)]
    cfg = ClipConfig(count=1, min_seconds=10, max_seconds=40)
    s, e = align_clip(segs, 1, 3, cfg)
    assert s == 0  # zurück auf den Satzanfang
    assert e == 4  # bis zum Satzende verlängert
    assert segs[e].text.endswith(".")


def test_clip_times_have_padding_without_overlapping_neighbours(transcript):
    clip = parse_selection({"clips": [suggestion(2, 9)]}, transcript, CFG)[0]
    seg_start = transcript.segments[2].start
    assert seg_start - 0.2 <= clip.start <= seg_start
    assert clip.start >= transcript.segments[1].end


def test_build_prompt_contains_ids_and_limits(transcript):
    prompt = build_prompt(transcript, CFG, 4)
    assert "[0]" in prompt and "[23]" in prompt
    assert "30 und 60 Sekunden" in prompt


def test_heuristic_produces_valid_clips(transcript):
    clips = parse_selection(heuristic_selection(transcript, CFG), transcript, CFG)
    assert 1 <= len(clips) <= CFG.count
    assert all(CFG.min_seconds * 0.8 <= c.duration <= CFG.max_seconds + 1 for c in clips)
