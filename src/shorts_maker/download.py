"""Schritt 1: Video laden (yt-dlp) oder lokale Datei übernehmen."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
from pathlib import Path

from .errors import DependencyError, DownloadError
from .models import VideoSource

log = logging.getLogger(__name__)


def ensure_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise DependencyError(
                f"'{tool}' wurde nicht gefunden.",
                hint="Installiere ffmpeg (z. B. 'sudo apt install ffmpeg' oder 'brew install ffmpeg').",
            )


def probe(path: Path) -> dict:
    """Liefert ffprobe-Metadaten (Breite, Höhe, Dauer, FPS) des ersten Videostreams."""
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
        str(path),
    ]
    try:
        out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError as exc:
        raise DownloadError(f"ffprobe konnte {path} nicht lesen: {exc.stderr.strip()}") from exc
    data = json.loads(out)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if video is None:
        raise DownloadError(f"{path} enthält keinen Videostream.")
    num, _, den = video.get("r_frame_rate", "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    return {
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": fps,
        "duration": float(data.get("format", {}).get("duration", 0.0)),
        "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", [])),
    }


def is_url(source: str) -> bool:
    return source.startswith(("http://", "https://", "www."))


def local_video_id(path: Path) -> str:
    st = path.stat()
    digest = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:10]
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in path.stem)[:40]
    return f"local-{stem}-{digest}"


def resolve_local(path: Path) -> VideoSource:
    if not path.is_file():
        raise DownloadError(f"Datei nicht gefunden: {path}")
    info = probe(path)
    return VideoSource(id=local_video_id(path), title=path.stem, path=path.resolve(), duration=info["duration"])


def fetch_info(url: str) -> dict:
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover - Pflichtabhängigkeit
        raise DependencyError("yt-dlp ist nicht installiert.", hint="pip install yt-dlp") from exc

    opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(
            f"Video-Infos konnten nicht geladen werden: {exc}",
            hint="Prüfe die URL und deine Internetverbindung; ggf. 'pip install -U yt-dlp'.",
        ) from exc


def download(url: str, target_dir: Path, info: dict | None = None) -> VideoSource:
    """Lädt das Video in bester Qualität (Video+Audio, als MP4 gemuxt) nach target_dir/source.mp4."""
    import yt_dlp

    info = info or fetch_info(url)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "source.mp4"
    source = VideoSource(
        id=info["id"], title=info.get("title") or info["id"], path=target, url=url, duration=info.get("duration")
    )
    if target.is_file() and target.stat().st_size > 0:
        log.info("Video bereits vorhanden: %s", target)
        return source

    log.info("Lade '%s' herunter …", source.title)
    opts = {
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": str(target_dir / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(f"Download fehlgeschlagen: {exc}") from exc

    if not target.is_file():
        # Falls yt-dlp ein anderes Containerformat geschrieben hat, nach MP4 remuxen.
        candidates = sorted(target_dir.glob("source.*"))
        if not candidates:
            raise DownloadError("yt-dlp hat keine Datei erzeugt.")
        _remux_to_mp4(candidates[0], target)
    return source


def _remux_to_mp4(src: Path, dst: Path) -> None:
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-c", "copy", str(dst)]
    if subprocess.run(cmd, capture_output=True).returncode != 0:
        # Kopieren nicht möglich (z. B. Opus-Audio) -> Audio neu kodieren
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-c:v", "copy", "-c:a", "aac", str(dst)]
        subprocess.run(cmd, check=True, capture_output=True)
    src.unlink(missing_ok=True)


def get_source(source: str, cache_root: Path) -> VideoSource:
    """Einstiegspunkt: URL -> Download in den Cache, Pfad -> lokale Datei."""
    ensure_ffmpeg()
    if is_url(source):
        info = fetch_info(source)
        return download(source, cache_root / info["id"], info)
    return resolve_local(Path(source).expanduser())
