"""Fehlertypen mit verständlichen Meldungen für die CLI."""


class YtclipsError(Exception):
    """Basisfehler; die Meldung wird dem Nutzer direkt angezeigt."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


class DependencyError(YtclipsError):
    """Ein externes Programm oder optionales Paket fehlt."""


class DownloadError(YtclipsError):
    """Das Video konnte nicht geladen werden."""


class TranscriptionError(YtclipsError):
    """Die Transkription ist fehlgeschlagen."""


class LLMError(YtclipsError):
    """Die Claude-API hat einen Fehler oder eine unbrauchbare Antwort geliefert."""


class SelectionError(YtclipsError):
    """Aus der Antwort ließen sich keine gültigen Clips ableiten."""


class ExportError(YtclipsError):
    """ffmpeg ist beim Rendern eines Clips fehlgeschlagen."""
