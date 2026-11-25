import pytest

from ytclips.config import load_settings
from ytclips.errors import YtclipsError


def test_cli_overrides_without_config_file_ignore_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = load_settings(None, {"clips": {"count": None, "max_seconds": None}, "whisper": {"model": None}})
    assert s.clips.count == 5 and s.clips.max_seconds == 60
    assert s.whisper.model == "large-v3"


def test_yaml_and_overrides_are_merged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "clips:\n  count: 3\n  min_seconds: 20\nsubtitles:\n  highlight_color: '#00ff00'\n", encoding="utf-8"
    )
    s = load_settings(None, {"clips": {"count": 7, "min_seconds": None}})
    assert s.clips.count == 7
    assert s.clips.min_seconds == 20
    assert s.subtitles.highlight_color == "#00FF00"


def test_invalid_values_raise_readable_error(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("clips:\n  min_seconds: 90\n  max_seconds: 60\n", encoding="utf-8")
    with pytest.raises(YtclipsError, match="Ungültige Konfiguration"):
        load_settings(cfg)


def test_missing_config_file(tmp_path):
    with pytest.raises(YtclipsError, match="nicht gefunden"):
        load_settings(tmp_path / "fehlt.yaml")
