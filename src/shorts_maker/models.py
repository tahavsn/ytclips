"""Gemeinsame Datentypen der Pipeline."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class Word(BaseModel):
    start: float
    end: float
    text: str


class Segment(BaseModel):
    start: float
    end: float
    text: str
    words: list[Word] = Field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


class Transcript(BaseModel):
    language: str
    duration: float
    segments: list[Segment]

    def words(self) -> list[Word]:
        return [w for s in self.segments for w in s.words]


class VideoSource(BaseModel):
    id: str
    title: str
    path: Path
    url: str | None = None
    duration: float | None = None


class ClipCandidate(BaseModel):
    """Ein ausgewählter Abschnitt, bereits an Satzgrenzen ausgerichtet."""

    start: float
    end: float
    title: str
    hook: str = ""
    reason: str = ""
    score: float = 0.0

    @property
    def duration(self) -> float:
        return self.end - self.start


class ClipResult(BaseModel):
    index: int
    file: str
    start: float
    end: float
    duration: float
    title: str
    hook: str
    reason: str
    score: float
    subtitle_file: str
    crop_mode: str
