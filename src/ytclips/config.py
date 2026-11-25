"""Konfiguration: Defaults < config.yaml < CLI-Optionen. Secrets kommen aus .env."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .errors import YtclipsError

log = logging.getLogger(__name__)

DEFAULT_CONFIG_FILES = ("config.yaml", "config.yml")


class DownloadConfig(BaseModel):
    # "default" = Standard-Clients von yt-dlp; "web_embedded" hilft gegen die Bot-Sperre
    player_clients: list[str] = ["default", "web_embedded"]
    cookies_file: Path | None = None
    cookies_from_browser: str | None = None  # z. B. "firefox", "chrome"


class WhisperConfig(BaseModel):
    model: str = "large-v3"
    device: str = "auto"
    compute_type: str = "auto"
    beam_size: int = 5
    vad_filter: bool = True


class LLMConfig(BaseModel):
    model: str = "claude-opus-5-5"
    translate_effort: str = "medium"
    select_effort: str = "high"
    # Segmente pro Übersetzungsanfrage
    translate_batch_size: int = 80


class ClipConfig(BaseModel):
    count: int = Field(5, ge=1, le=50)
    min_seconds: float = Field(30.0, gt=0)
    max_seconds: float = Field(60.0, gt=0)

    @model_validator(mode="after")
    def _check_range(self) -> "ClipConfig":
        if self.min_seconds > self.max_seconds:
            raise ValueError("clips.min_seconds darf nicht größer als clips.max_seconds sein")
        return self


class SubtitleConfig(BaseModel):
    font: str = "Arial"
    fonts_dir: Path | None = None
    font_size: int = 82
    bold: bool = True
    uppercase: bool = False
    text_color: str = "#FFFFFF"
    highlight_color: str = "#FFE400"
    outline_color: str = "#000000"
    outline: float = 6
    shadow: float = 2
    margin_v: int = 480
    margin_h: int = 70
    # Zeilenlänge für die Anzeige im 9:16-Video (große Schrift)
    max_chars_per_line: int = 20
    max_lines: int = 2
    # Neue Untertitel-Seite nach dieser Sprechpause (Sekunden)
    pause_break: float = 0.6
    highlight_scale: int = 110

    @field_validator("text_color", "highlight_color", "outline_color")
    @classmethod
    def _hex(cls, v: str) -> str:
        s = v.lstrip("#")
        if len(s) != 6 or any(c not in "0123456789abcdefABCDEF" for c in s):
            raise ValueError(f"Farbe muss im Format #RRGGBB angegeben werden, nicht {v!r}")
        return "#" + s.upper()


class TranslationConfig(BaseModel):
    max_chars_per_line: int = 42
    max_lines: int = 2


class CropConfig(BaseModel):
    face_tracking: bool = True
    face_model: str = "full"  # "full" (auch kleine Gesichter) oder "short" (Nahaufnahmen)
    sample_fps: float = 4.0
    # Kamera bewegt sich erst, wenn das Gesicht so weit (Anteil der Bildbreite) abweicht
    deadzone: float = 0.08
    min_detection_confidence: float = 0.5


class ExportConfig(BaseModel):
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 20
    preset: str = "medium"
    audio_bitrate: str = "160k"
    loudnorm: bool = True


class Settings(BaseModel):
    download: DownloadConfig = DownloadConfig()
    whisper: WhisperConfig = WhisperConfig()
    llm: LLMConfig = LLMConfig()
    clips: ClipConfig = ClipConfig()
    subtitles: SubtitleConfig = SubtitleConfig()
    translation: TranslationConfig = TranslationConfig()
    crop: CropConfig = CropConfig()
    export: ExportConfig = ExportConfig()
    target_language: str = "de"
    cache_dir: Path = Path(".cache/ytclips")

    @property
    def anthropic_api_key(self) -> str | None:
        return os.environ.get("ANTHROPIC_API_KEY") or None


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merged `override` in `base`; None-Werte (nicht gesetzte CLI-Optionen) werden ignoriert."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict):
            out[key] = _deep_merge(out[key] if isinstance(out.get(key), dict) else {}, value)
        elif value is not None:
            out[key] = value
    return out


def load_settings(config_path: Path | None = None, overrides: dict[str, Any] | None = None) -> Settings:
    """Lädt .env, optional config.yaml und wendet CLI-Overrides an."""
    load_dotenv()

    data: dict[str, Any] = {}
    path = config_path
    if path is None:
        path = next((Path(p) for p in DEFAULT_CONFIG_FILES if Path(p).is_file()), None)
    elif not path.is_file():
        raise YtclipsError(f"Konfigurationsdatei nicht gefunden: {path}")

    if path is not None:
        log.debug("Lade Konfiguration aus %s", path)
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise YtclipsError(f"{path} ist kein gültiges YAML: {exc}") from exc
        if not isinstance(loaded, dict):
            raise YtclipsError(f"{path} muss ein YAML-Mapping enthalten.")
        data = loaded

    if overrides:
        data = _deep_merge(data, overrides)

    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise YtclipsError(f"Ungültige Konfiguration:\n{exc}") from exc
