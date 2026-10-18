"""Fehlertypen mit verständlichen Meldungen für die CLI."""


class ShortsMakerError(Exception):
    """Basisfehler; die Meldung wird dem Nutzer direkt angezeigt."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


class DependencyError(ShortsMakerError):
    """Ein externes Programm oder optionales Paket fehlt."""


class DownloadError(ShortsMakerError):
    """Das Video konnte nicht geladen werden."""


class TranscriptionError(ShortsMakerError):
    """Die Transkription ist fehlgeschlagen."""


class LLMError(ShortsMakerError):
    """Die Claude-API hat einen Fehler oder eine unbrauchbare Antwort geliefert."""


class SelectionError(ShortsMakerError):
    """Aus der Antwort ließen sich keine gültigen Clips ableiten."""


class ExportError(ShortsMakerError):
    """ffmpeg ist beim Rendern eines Clips fehlgeschlagen."""
