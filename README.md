# UdeA Zoom Recording Downloader

Descarga automática e incremental de grabaciones Zoom desde Moodle (UdeArroba).

## Estructura de Archivos

```
zoom-downloader/
├── config.json          # Configuración de asignaturas y URLs
├── scraper.py           # Extrae links de Zoom desde Moodle
├── downloader.py        # Descarga grabaciones con yt-dlp
├── run.ps1              # Script principal (PowerShell)
├── requirements.txt
├── recordings.json      # [auto] Links extraídos por el scraper
├── .browser-data/       # [auto] Cookies de Playwright
└── downloads/           # [auto] Grabaciones descargadas
    ├── calidad-de-software/
    │   ├── Grabacion 1.mp4
    │   ├── Grabacion 1.es.vtt    ← Transcripción
    │   └── Grabacion 2.mp4
    ├── ingenieria-web/
    ├── optimizacion/
    ├── seguridad-de-la-informacion/
    └── transcripts/              ← Copia centralizada de transcripciones
        ├── calidad-de-software/
        │   └── Grabacion 1.es.vtt
        └── ...
```

## Setup

```powershell
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Instalar browser para Playwright
python -m playwright install chromium
```

## Uso

### Opción 1: Script todo-en-uno (recomendado)
```powershell
.\run.ps1                                    # Scrape + descarga todo
.\run.ps1 -Course "calidad-de-software"      # Solo una asignatura
.\run.ps1 -SkipScrape                        # Solo descarga (sin re-scrape)
.\run.ps1 -DryRun                            # Simular sin descargar
.\run.ps1 -Status                            # Ver estado
```

### Opción 2: Paso a paso
```powershell
# Fase 1: Extraer links (abre browser, login manual la primera vez)
python scraper.py

# Fase 2: Descargar grabaciones
python downloader.py

# Ver estado
python downloader.py --status
```

## Idempotencia

- El scraper hace **merge incremental**: no pierde links anteriores al re-ejecutar.
- El downloader usa `--download-archive` de yt-dlp: nunca re-descarga un archivo ya bajado.
- Podés ejecutar `.\run.ps1` cuantas veces quieras, solo descarga lo nuevo.

## Para el Agente de IA

Las transcripciones están centralizadas en `downloads/transcripts/` organizadas por asignatura.
Cada archivo `.vtt` es parseable como texto plano (formato WebVTT con timestamps).

## Notas

- El primer `scraper.py` abre un browser real para login manual en Moodle.
- Las cookies se guardan en `.browser-data/` para sesiones futuras.
- Si la sesión de Moodle expira, el scraper detecta y pide login de nuevo.
- yt-dlp se encarga de nombrar los archivos según el título de la grabación en Zoom.
