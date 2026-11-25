"""Schritt 5: 9:16-Crop – mit MediaPipe-Gesichtstracking oder als Center-Crop.

Ablauf beim Tracking:
1. Frames des Clips mit `sample_fps` abtasten, Gesichter erkennen (MediaPipe).
2. Pro Sample die x-Mitte des Hauptsprechers bestimmen (größtes Gesicht,
   bevorzugt nahe an der vorherigen Position).
3. Glätten (Median) und "Deadzone-Kamera": die virtuelle Kamera bewegt sich erst,
   wenn der Sprecher deutlich und anhaltend aus der Mitte wandert. Das ergibt
   ruhige Einstellungen statt Zittern.
4. Keyframes -> stückweise lineare ffmpeg-Expression für den crop-Filter.
"""

from __future__ import annotations

import contextlib
import logging
import os
import statistics
import sys
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .config import CropConfig

log = logging.getLogger(__name__)

# "full" erkennt auch kleine Gesichter in Totalen (Podcasts, Bühnen), "short" ist für Selfie-Nähe.
MODEL_URLS = {
    "full": "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_full_range/float16/latest/blaze_face_full_range.tflite",
    "short": "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/latest/blaze_face_short_range.tflite",
}
DETECT_WIDTH = 960  # Frames werden für die Erkennung auf diese Breite verkleinert
TRANSITION = 0.35  # Sekunden für einen Kameraschwenk
CUT_THRESHOLD = 0.25  # Sprung > 25 % der Bildbreite = Szenenwechsel -> harter Schnitt


@dataclass
class CropPlan:
    src_w: int
    src_h: int
    crop_w: int
    crop_h: int
    y: int
    keyframes: list[tuple[float, float]] = field(default_factory=list)  # (t, x links)
    mode: str = "center"

    def x_expr(self) -> str:
        """ffmpeg-Expression für x in Abhängigkeit von t (stückweise linear)."""
        if not self.keyframes:
            return str((self.src_w - self.crop_w) // 2)
        kf = self.keyframes
        expr = f"{kf[-1][1]:.1f}"
        for (t0, x0), (t1, x1) in reversed(list(zip(kf, kf[1:]))):
            if abs(x1 - x0) < 0.5 or t1 - t0 < 1e-3:
                seg = f"{x0:.1f}"
            else:
                seg = f"{x0:.1f}+({x1 - x0:.1f})*(t-{t0:.3f})/{t1 - t0:.3f}"
            expr = f"if(lt(t,{t1:.3f}),{seg},{expr})"
        return expr

    def filter(self) -> str:
        return f"crop={self.crop_w}:{self.crop_h}:'{self.x_expr()}':{self.y}"


def crop_size(width: int, height: int, aspect: float = 9 / 16) -> tuple[int, int]:
    """Größtmöglicher Ausschnitt mit Seitenverhältnis `aspect` (gerade Pixelzahlen)."""
    crop_w = int(height * aspect) // 2 * 2
    crop_h = height // 2 * 2
    if crop_w > width:
        crop_w = width // 2 * 2
        crop_h = int(width / aspect) // 2 * 2
    return crop_w, crop_h


def center_plan(width: int, height: int) -> CropPlan:
    cw, ch = crop_size(width, height)
    return CropPlan(width, height, cw, ch, (height - ch) // 2, [], "center")


# --------------------------------------------------------------------------- Glättung


def fill_gaps(samples: list[tuple[float, float | None]]) -> list[tuple[float, float]] | None:
    """Ersetzt fehlende Erkennungen durch den letzten (bzw. nächsten) bekannten Wert."""
    known = [x for _, x in samples if x is not None]
    if not known:
        return None
    out: list[tuple[float, float]] = []
    last = known[0]
    for t, x in samples:
        if x is not None:
            last = x
        out.append((t, last))
    return out


def median_filter(values: list[float], window: int = 5) -> list[float]:
    half = window // 2
    return [statistics.median(values[max(0, i - half) : i + half + 1]) for i in range(len(values))]


def smooth_track(
    samples: list[tuple[float, float | None]],
    frame_w: int,
    crop_w: int,
    deadzone: float = 0.08,
    min_hits: int = 2,
) -> list[tuple[float, float]]:
    """Wandelt rohe Gesichts-x-Mitten in ruhige Kamera-Keyframes (t, x_links)."""
    filled = fill_gaps(samples)
    if not filled:
        return []
    times = [t for t, _ in filled]
    centers = median_filter([x for _, x in filled])
    max_x = frame_w - crop_w

    def left(cx: float) -> float:
        return float(min(max(cx - crop_w / 2, 0), max_x))

    threshold = deadzone * frame_w
    cam = centers[0]
    keyframes = [(times[0], left(cam))]
    hits = 0
    first_hit_t = times[0]
    for t, cx in zip(times, centers):
        if abs(cx - cam) > threshold:
            if hits == 0:
                first_hit_t = t
            hits += 1
            if hits >= min_hits:
                # Bewegung ab dem ersten Treffer; große Sprünge (Szenenwechsel) als harter Schnitt
                is_cut = abs(cx - cam) > CUT_THRESHOLD * frame_w
                keyframes.append((first_hit_t, left(cam)))
                cam = cx
                keyframes.append((first_hit_t + (0.001 if is_cut else TRANSITION), left(cam)))
                hits = 0
        else:
            hits = 0
    # Doppelte/rückwärts laufende Zeiten bereinigen
    cleaned: list[tuple[float, float]] = []
    for t, x in keyframes:
        if cleaned and t <= cleaned[-1][0]:
            cleaned[-1] = (cleaned[-1][0], x)
        else:
            cleaned.append((round(t, 3), round(x, 1)))
    return cleaned


# --------------------------------------------------------------------------- Erkennung


def _model_path(cache_root: Path, variant: str) -> Path:
    if variant not in MODEL_URLS:
        raise ValueError(f"Unbekanntes Gesichtsmodell {variant!r} (erlaubt: {', '.join(MODEL_URLS)})")
    path = cache_root / "models" / f"blaze_face_{variant}_range.tflite"
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        log.info("Lade MediaPipe-Gesichtsmodell (%s-range) …", variant)
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(MODEL_URLS[variant], tmp)
        tmp.replace(path)
    return path


def _pick_face(faces: list[tuple[float, float]], prev: float | None, frame_w: int) -> float | None:
    """faces: Liste (x_mitte, fläche). Größtes Gesicht, mit Bonus für Nähe zur letzten Position."""
    if not faces:
        return None
    if prev is None:
        return max(faces, key=lambda f: f[1])[0]
    return max(faces, key=lambda f: f[1] * (1.0 - 0.5 * min(1.0, abs(f[0] - prev) / frame_w)))[0]


def detect_faces(video: Path, start: float, end: float, cfg: CropConfig, cache_root: Path) -> list[tuple[float, float | None]]:
    """Gibt (t relativ zum Clipstart, x-Mitte des Hauptgesichts oder None) zurück."""
    os.environ.setdefault("GLOG_minloglevel", "2")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    import cv2
    import mediapipe as mp
    from mediapipe.tasks.python import vision
    from mediapipe.tasks.python.core.base_options import BaseOptions

    options = vision.FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(_model_path(cache_root, cfg.face_model))),
        running_mode=vision.RunningMode.IMAGE,
        min_detection_confidence=cfg.min_detection_confidence,
    )
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV kann {video} nicht öffnen")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    step = max(1, round(fps / cfg.sample_fps))
    scale = min(1.0, DETECT_WIDTH / frame_w) if frame_w else 1.0
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)

    samples: list[tuple[float, float | None]] = []
    prev: float | None = None
    with vision.FaceDetector.create_from_options(options) as detector:
        frame_idx = 0
        while True:
            pos = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if pos > end:
                break
            if frame_idx % step:
                if not cap.grab():
                    break
                frame_idx += 1
                continue
            ok, frame = cap.read()
            if not ok:
                break
            frame_idx += 1
            if scale < 1.0:
                frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            faces = [
                (
                    (d.bounding_box.origin_x + d.bounding_box.width / 2) / scale,
                    d.bounding_box.width * d.bounding_box.height / scale**2,
                )
                for d in result.detections
            ]
            prev_pick = _pick_face(faces, prev, frame_w)
            if prev_pick is not None:
                prev = prev_pick
            samples.append((max(0.0, pos - start), prev_pick))
    cap.release()
    return samples


@contextlib.contextmanager
def _quiet_native_stderr() -> Iterator[None]:
    """Unterdrückt die C++-Logausgaben von MediaPipe/LiteRT (außer bei --verbose)."""
    if log.isEnabledFor(logging.DEBUG):
        yield
        return
    try:
        fd = sys.stderr.fileno()
    except (AttributeError, OSError, ValueError):  # z. B. in Tests ohne echtes stderr
        yield
        return
    sys.stderr.flush()
    saved = os.dup(fd)
    try:
        with open(os.devnull, "w") as devnull:
            os.dup2(devnull.fileno(), fd)
            yield
    finally:
        sys.stderr.flush()
        os.dup2(saved, fd)
        os.close(saved)


def plan_crop(video: Path, start: float, end: float, width: int, height: int, cfg: CropConfig,
              cache_root: Path) -> CropPlan:
    """Erstellt den Crop-Plan; fällt bei Problemen still auf Center-Crop zurück."""
    plan = center_plan(width, height)
    if not cfg.face_tracking or plan.crop_w >= width:
        return plan
    try:
        _model_path(cache_root, cfg.face_model)  # Download außerhalb der Umleitung (Fehler sichtbar)
        with _quiet_native_stderr():
            samples = detect_faces(video, start, end, cfg, cache_root)
    except ImportError:
        log.warning("MediaPipe/OpenCV nicht installiert – nutze Center-Crop (pip install 'ytclips[face]').")
        return plan
    except Exception as exc:  # Modell-Download, Codec-Probleme, …
        log.warning("Gesichtstracking fehlgeschlagen (%s) – nutze Center-Crop.", exc)
        return plan

    hits = sum(1 for _, x in samples if x is not None)
    if not samples or hits / len(samples) < 0.2:
        log.info("Kaum Gesichter erkannt (%d/%d Samples) – nutze Center-Crop.", hits, len(samples))
        return plan

    keyframes = smooth_track(samples, width, plan.crop_w, cfg.deadzone)
    log.info("Gesichtstracking: %d/%d Samples mit Gesicht, %d Keyframes.", hits, len(samples), len(keyframes))
    plan.keyframes = keyframes
    plan.mode = "face"
    return plan
