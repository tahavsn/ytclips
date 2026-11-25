"""Schritt 7: Clip schneiden, croppen, skalieren, Untertitel einbrennen, H.264/AAC exportieren."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .config import ExportConfig, SubtitleConfig
from .crop import CropPlan
from .errors import ExportError

log = logging.getLogger(__name__)


def _escape_filter_path(path: Path) -> str:
    """Pfad für Filteroptionen (ass=..., fontsdir=...) escapen."""
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def build_command(
    source: Path,
    output: Path,
    start: float,
    end: float,
    plan: CropPlan,
    ass_file: Path | None,
    cfg: ExportConfig,
    sub_cfg: SubtitleConfig | None = None,
    has_audio: bool = True,
) -> list[str]:
    vf = [plan.filter(), f"scale={cfg.width}:{cfg.height}:flags=lanczos", "setsar=1", f"fps={cfg.fps}"]
    if ass_file is not None:
        ass = f"ass='{_escape_filter_path(ass_file)}'"
        if sub_cfg is not None and sub_cfg.fonts_dir:
            ass += f":fontsdir='{_escape_filter_path(Path(sub_cfg.fonts_dir))}'"
        vf.append(ass)

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(source),
        "-vf", ",".join(vf),
        "-c:v", "libx264", "-preset", cfg.preset, "-crf", str(cfg.crf),
        "-profile:v", "high", "-pix_fmt", "yuv420p",
    ]
    if has_audio:
        if cfg.loudnorm:
            cmd += ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]
        cmd += ["-c:a", "aac", "-b:a", cfg.audio_bitrate, "-ar", "48000", "-ac", "2"]
    else:
        cmd += ["-an"]
    cmd += ["-movflags", "+faststart", str(output)]
    return cmd


def render_clip(
    source: Path,
    output: Path,
    start: float,
    end: float,
    plan: CropPlan,
    ass_file: Path | None,
    cfg: ExportConfig,
    sub_cfg: SubtitleConfig | None = None,
    has_audio: bool = True,
) -> Path:
    cmd = build_command(source, output, start, end, plan, ass_file, cfg, sub_cfg, has_audio)
    log.debug("ffmpeg: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not output.is_file():
        tail = "\n".join(proc.stderr.strip().splitlines()[-8:])
        raise ExportError(f"ffmpeg konnte {output.name} nicht erzeugen:\n{tail}")
    return output
