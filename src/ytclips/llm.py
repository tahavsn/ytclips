"""Dünne Hülle um die Anthropic-API für strukturierte (JSON-)Antworten."""

from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel

from .config import Settings
from .errors import LLMError

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Bei einer Ablehnung durch Sicherheitsklassifikatoren übernimmt serverseitig
# automatisch ein passendes Fallback-Modell.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def make_client(settings: Settings):
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - Pflichtabhängigkeit
        raise LLMError("Das Paket 'anthropic' ist nicht installiert.", hint="pip install anthropic") from exc
    if not settings.anthropic_api_key:
        raise LLMError(
            "ANTHROPIC_API_KEY ist nicht gesetzt.",
            hint="Lege eine .env-Datei mit ANTHROPIC_API_KEY=... an (siehe .env.example) "
            "oder nutze --selector heuristic und --no-translate für einen Offline-Lauf.",
        )
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=4)


def structured(
    client,
    *,
    model: str,
    system: str,
    prompt: str,
    schema: type[T],
    effort: str = "medium",
    max_tokens: int = 16000,
) -> T:
    """Schickt einen Prompt und gibt die gegen `schema` validierte Antwort zurück."""
    import anthropic

    try:
        response = client.beta.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
            output_config={"effort": effort},
            thinking={"type": "adaptive"},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as exc:
        raise LLMError("Die Anthropic-API hat den API-Schlüssel abgelehnt.", hint="Prüfe ANTHROPIC_API_KEY.") from exc
    except anthropic.NotFoundError as exc:
        raise LLMError(f"Modell '{model}' ist nicht verfügbar: {exc}", hint="Setze llm.model in config.yaml.") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError("Rate-Limit der Anthropic-API erreicht.", hint="Warte kurz und starte erneut.") from exc
    except anthropic.BadRequestError as exc:
        raise LLMError(f"Ungültige Anfrage an die Anthropic-API: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"Anthropic-API-Fehler ({exc.status_code}): {exc}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError("Keine Verbindung zur Anthropic-API.", hint="Prüfe deine Internetverbindung.") from exc

    usage = response.usage
    log.debug("LLM usage: in=%s out=%s", usage.input_tokens, usage.output_tokens)

    if response.stop_reason == "refusal":
        raise LLMError("Claude hat die Anfrage abgelehnt (stop_reason=refusal).")
    if response.stop_reason == "max_tokens":
        raise LLMError("Die Antwort wurde abgeschnitten (max_tokens erreicht).", hint="Verkleinere die Batch-Größe.")
    parsed = response.parsed_output
    if parsed is None:
        raise LLMError("Claude hat keine auswertbare JSON-Antwort geliefert.")
    return parsed
