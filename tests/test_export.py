from pathlib import Path

from ytclips.config import ExportConfig, SubtitleConfig
from ytclips.crop import center_plan
from ytclips.export import build_command
from ytclips.pipeline import slugify


def test_build_command_contains_all_stages():
    cmd = build_command(
        Path("in.mp4"), Path("out.mp4"), 10.0, 40.5, center_plan(1920, 1080), Path("/tmp/a:b.ass"),
        ExportConfig(), SubtitleConfig(fonts_dir=Path("/fonts")),
    )
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.startswith("crop=606:1080:")
    assert "scale=1080:1920" in vf
    assert "ass='/tmp/a\\:b.ass':fontsdir='/fonts'" in vf
    assert cmd[cmd.index("-ss") + 1] == "10.000" and cmd[cmd.index("-to") + 1] == "40.500"
    assert "libx264" in cmd and "aac" in cmd and "+faststart" in cmd
    assert any(a.startswith("loudnorm") for a in cmd)


def test_build_command_without_audio():
    cmd = build_command(Path("in.mp4"), Path("out.mp4"), 0, 5, center_plan(1920, 1080), None,
                        ExportConfig(), has_audio=False)
    assert "-an" in cmd and "aac" not in cmd


def test_slugify():
    assert slugify("Größter Fehler: Warum 90% scheitern!") == "groesster-fehler-warum-90-scheitern"
    assert slugify("???") == "clip"
