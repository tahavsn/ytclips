# ytclips

Open-Source-Tool, das YouTube-Videos (oder lokale Videodateien) automatisch in **vertikale Short-Clips
(9:16, 1080×1920)** mit **eingebrannten deutschen Untertiteln** im TikTok-Stil umwandelt – fertig für
YouTube Shorts, Instagram Reels und TikTok.

```
YouTube-URL ──► Download ──► Transkription ──► Übersetzung ──► Clip-Auswahl ──► 9:16-Crop ──► Untertitel ──► MP4
               (yt-dlp)    (faster-whisper)   (Claude API)    (Claude API)    (MediaPipe)    (ASS/libass)   (ffmpeg)
```

**Ausgabe:** N fertige MP4-Clips (30–60 s) plus `clips.json` mit Start/Ende, Titel, Hook und Begründung
der Auswahl.

## Features

- **Download** in bester Qualität per [yt-dlp](https://github.com/yt-dlp/yt-dlp) – oder lokale Datei als Eingabe
- **Transkription** mit [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (`large-v3`,
  Wort-Zeitstempel, automatische Spracherkennung, VAD)
- **Übersetzung** ins Deutsche per Claude API – kurze, gut lesbare Untertitel (max. 2 Zeilen à ~42 Zeichen),
  Zeitstempel bleiben erhalten
- **Clip-Auswahl** per Claude: starker Hook, in sich abgeschlossen, 30–60 s, Schnitt immer an Satzgrenzen
- **Gesichtstracking** mit MediaPipe: der Sprecher bleibt im 9:16-Ausschnitt zentriert (ruhige
  „Deadzone-Kamera“, harte Schnitte bei Szenenwechseln, Fallback: Center-Crop)
- **Untertitel im TikTok-Stil**: große Schrift, dicke Outline, unteres Drittel,
  **Wort-für-Wort-Highlighting**
- **Export** als H.264/AAC-MP4 (High Profile, yuv420p, 30 fps, `faststart`, Lautheit auf −14 LUFS normalisiert)
- **Cache** für Transkript, Übersetzung und Auswahl – Re-Runs sind schnell und kosten keine API-Tokens
- **Offline-Modus** (`--selector heuristic --no-translate`) ganz ohne API-Key

## Installation

### 1. Voraussetzungen

- **Python 3.11+**
- **ffmpeg** (mit libass – bei allen gängigen Builds dabei)

| System | Befehl |
| --- | --- |
| Ubuntu/Debian | `sudo apt install ffmpeg` |
| macOS (Homebrew) | `brew install ffmpeg` |
| Windows | `winget install ffmpeg` oder [ffmpeg.org](https://ffmpeg.org/download.html) (Ordner `bin` zum `PATH` hinzufügen) |

Prüfen: `ffmpeg -version` und `ffmpeg -filters | grep ass`.

> **Linux-Server ohne Desktop:** MediaPipe benötigt `libEGL`/`libGLES`:
> `sudo apt install libegl1 libgles2`. Fehlen sie, fällt das Tool automatisch auf Center-Crop zurück.

### 2. Paket installieren

```bash
git clone https://github.com/tahavsn/ytclips.git
cd ytclips
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[face]"         # ohne Gesichtstracking: pip install -e .
```

### 3. API-Key hinterlegen

```bash
cp .env.example .env
# .env öffnen und ANTHROPIC_API_KEY=sk-ant-... eintragen
```

Den Key bekommst du in der [Claude Console](https://console.anthropic.com/). Ohne Key funktioniert nur
der Offline-Modus.

### Optional: GPU

faster-whisper nutzt automatisch CUDA, wenn verfügbar (cuBLAS + cuDNN nötig, siehe
[faster-whisper-Doku](https://github.com/SYSTRAN/faster-whisper#gpu)). `large-v3` auf der CPU
funktioniert, ist aber langsam – für schnelle Tests `--whisper-model small` verwenden.

## Nutzung

```bash
ytclips run <youtube-url|datei> [OPTIONEN]
```

| Option | Beschreibung | Standard |
| --- | --- | --- |
| `-n, --clips` | Anzahl der Clips | 5 |
| `-l, --lang` | Zielsprache der Untertitel | `de` |
| `-o, --output` | Ausgabeordner | `./out` |
| `-c, --config` | Pfad zu einer `config.yaml` | `./config.yaml`, falls vorhanden |
| `--min-len` / `--max-len` | Clip-Länge in Sekunden | 30 / 60 |
| `--whisper-model` | faster-whisper-Modell (`tiny` … `large-v3`) | `large-v3` |
| `--source-lang` | Quellsprache erzwingen (statt Auto-Erkennung) | – |
| `--selector` | `claude` oder `heuristic` (offline) | `claude` |
| `--no-translate` | Untertitel in Originalsprache | aus |
| `--no-face-tracking` | Immer Center-Crop | aus |
| `--no-cache` | Zwischenergebnisse neu berechnen | aus |
| `-v, --verbose` | Ausführliche Logs | aus |

### Beispiele

```bash
# 5 Clips mit deutschen Untertiteln aus einem englischen Video
ytclips run "https://www.youtube.com/watch?v=VIDEO_ID" --clips 5 --lang de --output ./out

# Lokale Datei, 3 kurze Clips, schnelles Whisper-Modell
ytclips run ./podcast.mp4 -n 3 --min-len 20 --max-len 40 --whisper-model small

# Eigene Optik über eine Konfigurationsdatei
ytclips run "https://youtu.be/VIDEO_ID" -c config.yaml

# Komplett offline (ohne API-Key): Heuristik statt Claude, Untertitel in Originalsprache
ytclips run ./video.mp4 --selector heuristic --no-translate
```

### Ausgabe

```
out/<video-id>/
├── clip_01_warum-90-prozent-scheitern.mp4
├── clip_01_warum-90-prozent-scheitern.ass   # Untertitel (zum Nachbearbeiten)
├── clip_02_….mp4
├── …
└── clips.json
```

`clips.json` (gekürzt):

```json
{
  "source": { "id": "VIDEO_ID", "title": "…", "url": "https://…", "duration": 1834.2 },
  "source_language": "en",
  "subtitle_language": "de",
  "selector": "claude",
  "model": "claude-opus-5-5",
  "clips": [
    {
      "index": 1,
      "file": "clip_01_warum-90-prozent-scheitern.mp4",
      "start": 312.45,
      "end": 359.8,
      "duration": 47.35,
      "title": "Warum 90 % scheitern",
      "hook": "Fast alle machen diesen einen Fehler …",
      "reason": "Starker Einstieg mit Frage, klare Pointe am Ende, ohne Kontext verständlich.",
      "score": 92,
      "subtitle_file": "clip_01_warum-90-prozent-scheitern.ass",
      "crop_mode": "face"
    }
  ]
}
```

## Konfiguration

Alle Einstellungen sind optional. Kopiere [`config.example.yaml`](config.example.yaml) nach `config.yaml`
und passe an, was du brauchst. Reihenfolge: Defaults → `config.yaml` → CLI-Optionen.

```yaml
subtitles:
  font: "Montserrat ExtraBold"  # muss installiert sein – oder fonts_dir setzen
  fonts_dir: ./fonts            # Ordner mit .ttf/.otf
  font_size: 82
  text_color: "#FFFFFF"
  highlight_color: "#FFE400"    # Farbe des gerade gesprochenen Worts
  outline: 6
  margin_v: 480                 # Abstand vom unteren Rand -> unteres Drittel
  max_chars_per_line: 20        # Zeilenlänge im Video (große Schrift)
  uppercase: false

clips:
  count: 5
  min_seconds: 30
  max_seconds: 60

whisper:
  model: large-v3
```

**Zwei Zeilenlängen?** `translation.max_chars_per_line` (42) ist die Lesbarkeitsregel für die
Übersetzung: ein Segment passt in 2 × 42 Zeichen. `subtitles.max_chars_per_line` (20) bestimmt den
Umbruch im 9:16-Video: Bei großer Schrift passen nur ~20 Zeichen in eine Zeile, deshalb wird ein
Segment auf mehrere kurze „Seiten“ verteilt.

## Wie es funktioniert

| Modul | Aufgabe |
| --- | --- |
| `download.py` | yt-dlp lädt bestes Video + Audio und muxt es als MP4; lokale Dateien werden direkt verwendet |
| `transcribe.py` | faster-whisper mit Wort-Zeitstempeln; danach Neusegmentierung an Satzenden/Pausen (≤ 7 s, ≤ 84 Zeichen) |
| `translate.py` | Batches nummerierter Segmente → Claude (Structured Outputs). Fehlende Zeilen werden nachgefragt. Die Wortzeiten der Übersetzung werden auf die Sprechintervalle des Originals verteilt |
| `select.py` | Claude wählt Clips über **Segment-ids**, damit jeder Schnitt auf einer Segmentgrenze liegt. `parse_selection` validiert, zieht Start/Ende auf Satzgrenzen, korrigiert die Länge und filtert Überlappungen |
| `crop.py` | MediaPipe-Gesichtserkennung mit 4 fps, Median-Glättung und Deadzone-Kamera → zeitabhängige ffmpeg-`crop`-Expression |
| `subtitles.py` | Wörter → Seiten (≤ 2 Zeilen) → ein ASS-Event pro Wort mit hervorgehobenem aktivem Wort |
| `export.py` | ein ffmpeg-Durchlauf: Schnitt, Crop, Skalierung auf 1080×1920, Untertitel einbrennen, Encoding |
| `pipeline.py` | verbindet alles, nutzt den Cache in `.cache/ytclips/<video-id>/` |

Claude wird als `claude-opus-5-5` mit adaptivem Thinking und Structured Outputs angesprochen. Falls
eine Anfrage von den Sicherheitsklassifikatoren abgelehnt wird, übernimmt serverseitig automatisch ein
Fallback-Modell (`fallbacks: "default"`). Modell und Effort sind über `llm.*` in der `config.yaml`
einstellbar.

## Entwicklung

```bash
pip install -e ".[face,dev]"
pytest
```

Die Unit-Tests decken das Parsen der Clip-Auswahl, die Untertitel-Formatierung, Crop-Glättung,
Übersetzungslogik (mit Fake-LLM), Konfiguration und den ffmpeg-Befehl ab. Sie brauchen weder Netzwerk
noch API-Key.

## Fehlerbehebung

| Problem | Lösung |
| --- | --- |
| `'ffmpeg' wurde nicht gefunden` | ffmpeg installieren und in den `PATH` aufnehmen |
| `ANTHROPIC_API_KEY ist nicht gesetzt` | `.env` anlegen oder Offline-Modus nutzen |
| Download schlägt fehl | `pip install -U yt-dlp` (YouTube ändert sich häufig) |
| Transkription sehr langsam | `--whisper-model small` oder GPU nutzen |
| Untertitel in falscher Schrift | Schrift installieren oder `subtitles.fonts_dir` setzen |
| Immer Center-Crop | `pip install -e ".[face]"`, unter Linux `libegl1 libgles2` installieren, mit `-v` Logs prüfen |

## Roadmap

- [ ] Sprecher-Diarisierung: bei mehreren Personen auf den aktiven Sprecher schneiden
- [ ] Split-Screen-Layout für Podcasts mit zwei Personen
- [ ] Blur-Hintergrund statt Crop für Inhalte ohne Personen (Screencasts, Folien)
- [ ] Emojis und Keyword-Hervorhebung in den Untertiteln
- [ ] Automatische Titel/Beschreibungen/Hashtags pro Plattform
- [ ] Hook-Text-Overlay in den ersten Sekunden
- [ ] Batch-Verarbeitung von Playlists und Kanälen
- [ ] Web-Oberfläche zum Vorschauen und Feinjustieren der Schnitte
- [ ] Direkter Upload zu YouTube/TikTok/Instagram
- [ ] Docker-Image mit GPU-Support

## Rechtliches

Lade nur Videos herunter und verarbeite nur Inhalte, für die du die Rechte hast oder deren Nutzung
erlaubt ist. Beachte die Nutzungsbedingungen von YouTube.

## Lizenz

[MIT](LICENSE)
