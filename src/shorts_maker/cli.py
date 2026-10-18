"""Kommandozeile: `shorts-maker run <url|datei> --clips 5 --lang de --output ./out`."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from . import __version__
from .config import load_settings
from .errors import ShortsMakerError

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Wandelt YouTube-Videos in vertikale Short-Clips (9:16) mit eingebrannten Untertiteln um.",
)
console = Console(stderr=True)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(console=console, show_path=verbose, rich_tracebacks=verbose, markup=False)],
        force=True,
    )
    for noisy in ("httpx", "httpx2", "anthropic", "faster_whisper", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING if not verbose else logging.INFO)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"shorts-maker {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        Optional[bool], typer.Option("--version", callback=_version, is_eager=True, help="Version anzeigen.")
    ] = None,
) -> None:
    """shorts-maker"""


@app.command()
def run(
    source: Annotated[str, typer.Argument(help="YouTube-URL oder Pfad zu einer lokalen Videodatei.")],
    clips: Annotated[Optional[int], typer.Option("--clips", "-n", min=1, max=50, help="Anzahl der Clips.")] = None,
    lang: Annotated[str, typer.Option("--lang", "-l", help="Zielsprache der Untertitel.")] = "de",
    output: Annotated[Path, typer.Option("--output", "-o", help="Ausgabeordner.")] = Path("./out"),
    config: Annotated[Optional[Path], typer.Option("--config", "-c", help="Pfad zu config.yaml.")] = None,
    min_len: Annotated[Optional[float], typer.Option("--min-len", help="Minimale Clip-Länge (s).")] = None,
    max_len: Annotated[Optional[float], typer.Option("--max-len", help="Maximale Clip-Länge (s).")] = None,
    whisper_model: Annotated[
        Optional[str], typer.Option("--whisper-model", help="faster-whisper-Modell, z. B. large-v3, small.")
    ] = None,
    source_lang: Annotated[
        Optional[str], typer.Option("--source-lang", help="Quellsprache erzwingen statt automatisch erkennen.")
    ] = None,
    selector: Annotated[
        str, typer.Option("--selector", help="Clip-Auswahl: 'claude' oder 'heuristic' (offline).")
    ] = "claude",
    no_translate: Annotated[bool, typer.Option("--no-translate", help="Untertitel in Originalsprache.")] = False,
    no_face: Annotated[bool, typer.Option("--no-face-tracking", help="Immer Center-Crop verwenden.")] = False,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Zwischenergebnisse neu berechnen.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Ausführliche Logs.")] = False,
) -> None:
    """Erzeugt Short-Clips aus einem Video."""
    _setup_logging(verbose)
    if selector not in ("claude", "heuristic"):
        raise typer.BadParameter("--selector muss 'claude' oder 'heuristic' sein.")

    overrides = {
        "target_language": lang,
        "clips": {"count": clips, "min_seconds": min_len, "max_seconds": max_len},
        "whisper": {"model": whisper_model},
        "crop": {"face_tracking": False} if no_face else {},
    }
    try:
        from .pipeline import run as run_pipeline

        settings = load_settings(config, overrides)
        meta_path = run_pipeline(
            source,
            settings,
            output,
            use_cache=not no_cache,
            translate_enabled=not no_translate,
            selector=selector,
            source_language=source_lang,
        )
    except ShortsMakerError as exc:
        console.print(f"[bold red]Fehler:[/] {exc}")
        if exc.hint:
            console.print(f"[yellow]Tipp:[/] {exc.hint}")
        raise typer.Exit(1) from None
    except KeyboardInterrupt:
        console.print("[yellow]Abgebrochen.[/]")
        raise typer.Exit(130) from None

    _print_summary(meta_path)


def _print_summary(meta_path: Path) -> None:
    import json

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    table = Table(title=f"{len(meta['clips'])} Clips aus „{meta['source']['title']}“")
    table.add_column("#", justify="right")
    table.add_column("Titel")
    table.add_column("Start", justify="right")
    table.add_column("Dauer", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Crop")
    for c in meta["clips"]:
        table.add_row(str(c["index"]), c["title"], f"{c['start']:.1f}s", f"{c['duration']:.1f}s",
                      f"{c['score']:.0f}", c["crop_mode"])
    Console().print(table)
    Console().print(f"Ausgabe: [bold]{meta_path.parent}[/] (Metadaten: {meta_path.name})")


if __name__ == "__main__":  # pragma: no cover
    app()
