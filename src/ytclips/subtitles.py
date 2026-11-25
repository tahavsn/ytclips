"""Schritt 6: ASS-Untertitel mit Wort-für-Wort-Highlighting (TikTok-Stil).

Die Wörter eines Clips werden zu "Seiten" (max. N Zeilen à M Zeichen) gruppiert.
Pro Wort entsteht ein Dialogue-Event, in dem genau dieses Wort hervorgehoben ist –
so springt das Highlight synchron zur Sprache von Wort zu Wort.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import SubtitleConfig
from .models import Transcript, Word
from .transcribe import ends_sentence

# Wie lange eine Seite nach dem letzten Wort stehen bleibt (falls Platz bis zur nächsten)
HOLD_AFTER = 0.4


@dataclass
class Page:
    lines: list[list[Word]] = field(default_factory=list)

    @property
    def words(self) -> list[Word]:
        return [w for line in self.lines for w in line]

    @property
    def start(self) -> float:
        return self.lines[0][0].start

    @property
    def last_end(self) -> float:
        return self.lines[-1][-1].end


def hex_to_ass(color: str, alpha: int = 0) -> str:
    """'#RRGGBB' -> '&HAABBGGRR' (ASS speichert Farben als BGR, Alpha 00 = deckend)."""
    s = color.lstrip("#")
    if len(s) != 6:
        raise ValueError(f"Ungültige Farbe: {color!r}")
    r, g, b = s[0:2], s[2:4], s[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def format_time(seconds: float) -> str:
    """Sekunden -> 'H:MM:SS.cc' (ASS nutzt Hundertstelsekunden)."""
    cs = max(0, int(round(seconds * 100)))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def escape_text(text: str) -> str:
    """Verhindert, dass Wörter als ASS-Override-Tags interpretiert werden."""
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def clip_words(transcript: Transcript, start: float, end: float) -> list[Word]:
    """Wörter im Zeitfenster [start, end], relativ zum Clipbeginn."""
    out = []
    for w in transcript.words():
        mid = (w.start + w.end) / 2
        if start <= mid <= end:
            out.append(
                Word(
                    start=round(max(0.0, w.start - start), 3),
                    end=round(min(end - start, w.end - start), 3),
                    text=w.text,
                )
            )
    return out


def build_pages(words: list[Word], max_chars: int, max_lines: int, pause_break: float) -> list[Page]:
    """Gruppiert Wörter zu Seiten: Zeilen <= max_chars, Seiten <= max_lines.

    Neue Seite bei Satzende, längerer Sprechpause oder wenn die Seite voll ist.
    """
    pages: list[Page] = []
    page = Page()
    line: list[Word] = []

    def line_len(ws: list[Word]) -> int:
        return sum(len(w.text) for w in ws) + max(0, len(ws) - 1)

    def close_page() -> None:
        nonlocal page, line
        if line:
            page.lines.append(line)
        if page.lines:
            pages.append(page)
        page, line = Page(), []

    prev: Word | None = None
    for word in words:
        if prev is not None:
            sentence_end = ends_sentence(prev.text)
            if sentence_end or word.start - prev.end >= pause_break:
                close_page()
        if line and line_len(line + [word]) > max_chars:
            page.lines.append(line)
            line = []
            if len(page.lines) >= max_lines:
                close_page()
        line.append(word)
        prev = word
    close_page()
    return pages


def _style_line(cfg: SubtitleConfig) -> str:
    bold = -1 if cfg.bold else 0
    return (
        f"Style: Default,{cfg.font},{cfg.font_size},"
        f"{hex_to_ass(cfg.text_color)},{hex_to_ass(cfg.highlight_color)},"
        f"{hex_to_ass(cfg.outline_color)},{hex_to_ass('#000000', 0x80)},"
        f"{bold},0,0,0,100,100,0,0,1,{cfg.outline:g},{cfg.shadow:g},2,"
        f"{cfg.margin_h},{cfg.margin_h},{cfg.margin_v},1"
    )


def _page_text(page: Page, active: int, cfg: SubtitleConfig) -> str:
    color = hex_to_ass(cfg.highlight_color)
    scale = cfg.highlight_scale
    rendered_lines = []
    idx = 0
    for line in page.lines:
        parts = []
        for w in line:
            text = escape_text(w.text.upper() if cfg.uppercase else w.text)
            if idx == active:
                tags = f"\\1c{color}"
                if scale != 100:
                    tags += f"\\fscx{scale}\\fscy{scale}"
                parts.append(f"{{{tags}}}{text}{{\\r}}")
            else:
                parts.append(text)
            idx += 1
        rendered_lines.append(" ".join(parts))
    return "\\N".join(rendered_lines)


def render_ass(words: list[Word], cfg: SubtitleConfig, width: int = 1080, height: int = 1920,
               duration: float | None = None) -> str:
    """Erzeugt den kompletten Inhalt einer .ass-Datei."""
    pages = build_pages(words, cfg.max_chars_per_line, cfg.max_lines, cfg.pause_break)
    events: list[str] = []
    for p_idx, page in enumerate(pages):
        next_start = pages[p_idx + 1].start if p_idx + 1 < len(pages) else None
        page_end = page.last_end + HOLD_AFTER
        if next_start is not None:
            page_end = min(page_end, next_start)
        if duration is not None:
            page_end = min(page_end, duration)
        page_end = max(page_end, page.last_end)

        page_words = page.words
        for k, word in enumerate(page_words):
            start = page.start if k == 0 else word.start
            end = page_words[k + 1].start if k + 1 < len(page_words) else page_end
            if end - start < 0.01:
                continue
            events.append(
                f"Dialogue: 0,{format_time(start)},{format_time(end)},Default,,0,0,0,,{_page_text(page, k, cfg)}"
            )

    header = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            _style_line(cfg),
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )
    return header + "\n" + "\n".join(events) + "\n"


def write_ass(path: Path, words: list[Word], cfg: SubtitleConfig, width: int, height: int,
              duration: float | None = None) -> Path:
    path.write_text(render_ass(words, cfg, width, height, duration), encoding="utf-8")
    return path
