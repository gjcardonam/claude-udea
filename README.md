<p align="center">
  <h1 align="center">claude_udea</h1>
  <p align="center">
    <strong>Transcripciones y asistente académico para la Universidad de Antioquia</strong>
  </p>
  <p align="center">
    Descarga y organiza grabaciones de Zoom desde Moodle e Ingenia; consulta las clases con IA
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-≥3.10-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/IA-Claude%20%7C%20Gemini%20%7C%20Ollama-orange?style=flat-square" alt="Claude, Gemini y Ollama">
    <img src="https://img.shields.io/badge/plataforma-Windows_|_macOS_|_Linux-green?style=flat-square" alt="Cross-platform">
  </p>
</p>

---

## Qué es

`claude_udea` es una herramienta de linea de comandos que:

1. **Busca** grabaciones de Zoom en Moodle (UdeArroba) e Ingenia (Virtual Ingeniería)
2. **Descarga y organiza** videos y transcripciones con metadata e índice por asignatura
3. **Abre** Claude Code, Gemini CLI u Ollama, o funciona sin asistente
4. **Genera transcripciones locales** con faster-whisper cuando Zoom no ofrece subtítulos
5. **Sincroniza materiales Moodle e Ingenia** como archivos, carpetas, páginas y adjuntos docentes cuando la cuenta tiene acceso

Todo en un solo comando: `claude_udea`

---

## Características

- **Sin navegador** -- login y scraping por HTTP directo, no necesita GUI ni Chromium
- **Moodle e Ingenia** -- obtiene fechas, duración y enlaces de las grabaciones
- **Materiales Moodle** -- recorre las secciones enlazadas del curso y sincroniza documentos y páginas en una carpeta separada
- **Materiales Ingenia** -- inicia sesión en el campus y recorre cursos autorizados
- **Pipeline paralelo** -- scrapea materias y descarga grabaciones simultaneamente
- **Setup interactivo** -- la primera vez te guia para configurar tus asignaturas
- **Asistentes flexibles** -- Claude Code, Gemini CLI, chat local con Ollama o modo sin asistente
- **Sesión persistente** -- restaura la sesión de Moodle y puede volver a iniciar sesión automáticamente
- **Descarga incremental** -- verifica en disco que el video exista antes de omitir una descarga
- **Paginación Moodle** -- recorre todas las páginas del listado de grabaciones de una actividad
- **Filtro por fechas** -- recorre el listado de Moodle por ventanas de 30 días para no perder las grabaciones antiguas (el listado oculta por defecto las de hace meses)
- **Subtítulos sin re-descargar** -- al reparar un video faltante no vuelve a bajar los subtítulos que ya están organizados
- **Deduplicacion por contenido** -- compara SHA-256 y respalda copias idénticas en vez de borrarlas
- **Recuperación de videos faltantes** -- re-descarga un video ausente aunque el registro o el archive lo marquen como descargado
- **Partes reales** -- conserva videos distintos de una misma sesión como `Clase #N - fecha - Parte M.mp4`
- **Reparación de nombres y duplicados** -- `--repair-videos --dry-run` previsualiza; al aplicar normaliza `Parte N`, respalda copias y vuelve a solicitar solo subtítulos Zoom faltantes
- **Transcripciones por parte** -- `.cc.vtt`, `.transcript.vtt`, `.chapter.vtt` y `.whisper.transcript.vtt` mantienen la misma fecha y parte que su video
- **Numeración independiente** -- Arquitectura de Software y Fábrica Escuela tienen secuencias separadas
- **Transcripción local opcional** -- faster-whisper procesa grabaciones sin subtítulos de Zoom
- **Cross-platform** -- funciona en Windows, macOS y Linux (incluido Raspberry Pi headless)
- **Skills de Claude** -- comandos especializados para estudiar con IA

---

## Requisitos

| Requisito | Para que | Como instalar |
|-----------|----------|---------------|
| **Python >= 3.10** | Ejecutar la herramienta | [python.org](https://www.python.org/downloads/) |
| **Node.js >= 18** | Instalar Claude Code o Gemini CLI automáticamente | [nodejs.org](https://nodejs.org/) (LTS) |
| **Git** | Clonar el repositorio | [git-scm.com](https://git-scm.com/) |

Las dependencias de Python, incluido `keyring` para el almacén seguro del sistema, se instalan automáticamente. Node.js solo es necesario para Claude Code o Gemini CLI. Ollama es opcional y se instala por separado.

Para ejecutar `transcribe_missing.py` se requieren además `faster-whisper`, FFmpeg y ffprobe. ffprobe también mejora la asociación de algunas descargas antiguas de Ingenia.

### Asistente AI

La primera vez que ejecutes `claude_udea`, puedes elegir Claude Code o Gemini CLI. Ollama se inicia con `--ollama`; `--no-assistant` ejecuta solo el pipeline de descargas.

| Asistente | Costo | Limite |
|-----------|-------|--------|
| **Gemini CLI** (Google) | Gratis | 1000 requests/dia con cuenta Google |
| **Claude Code** (Anthropic) | $20/mes (Pro) | Mejor calidad de respuestas |
| **Ollama** (local) | Gratis | Requiere instalar Ollama y descargar un modelo |

La selección de Claude o Gemini se guarda en `config.json`. Ollama es una opción por ejecución y no cambia esa preferencia.

---

## Instalacion

### Opcion 1: Desde GitHub (recomendado)

```bash
pip install git+https://github.com/JPUG26/claude-udea.git
```

### Opcion 2: Clonar y desarrollo local

```bash
git clone https://github.com/JPUG26/claude-udea.git
cd claude-udea
pip install -e .
```

### Nota para sistemas con Python externally-managed (Ubuntu 23+, Raspberry Pi OS, Fedora 38+)

Si ves el error `externally-managed-environment`, usa un entorno virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
pip install git+https://github.com/JPUG26/claude-udea.git
```

Para que el comando `claude_udea` este disponible globalmente, crea un symlink:

```bash
# Linux/macOS
ln -sf $(realpath .venv/bin/claude_udea) ~/.local/bin/claude_udea

# Verifica que ~/.local/bin este en tu PATH
echo $PATH | grep -q '.local/bin' && echo "OK" || echo "Agrega ~/.local/bin a tu PATH"
```

---

## Uso

### Primera vez

> **Antes de empezar**: tené listas las URLs de grabaciones de cada asignatura en Moodle o Ingenia. El setup pregunta la plataforma para cada materia.

#### Cómo conseguir el link de Moodle?

1. Entra a [UdeArroba](https://udearroba.udea.edu.co/)
2. Abri la asignatura
3. Busca la actividad de **Zoom** donde estan las grabaciones
4. Copia la URL de esa pagina -- es algo como `https://udearroba.udea.edu.co/mod/zoom/view.php?id=XXXXX`

Para Ingenia, copia la URL `https://ingenia.udea.edu.co/zoom/meeting/<ID>` o pega solo el número de reunión. No requiere inicio de sesión de Moodle.

#### Ejecutar

```bash
claude_udea
```

Se va a:

1. Verificar e instalar dependencias faltantes
2. Preguntar qué asistente querés usar (Gemini o Claude; Ollama se activa con `--ollama`)
3. Pedir plataforma y link de cada asignatura (solo la primera vez)
4. Pedir credenciales Moodle solo si hay materias de Moodle
5. Scrapear y descargar todo en paralelo
6. Abrir el asistente elegido, salvo que uses `--no-assistant`

### Ejecuciones siguientes

```bash
claude_udea              # Actualiza todo y abre el asistente configurado
```

Si la sesión de Moodle sigue activa, no vuelve a pedir credenciales. Ingenia no utiliza esa sesión.

Las ejecuciones normales también sincronizan materiales de las asignaturas Moodle. Para descargar solo documentos, sin ejecutar el pipeline de grabaciones ni abrir un asistente:

```bash
claude_udea --sync-materials
```

También puedes limitarlo a una asignatura, por ejemplo `claude_udea --sync-materials arquitectura-de-software`.

### Claude Code y Gemini CLI

Edita `~/claude-udea/config.json` (o `C:\claude-udea\config.json` en Windows) y cambia `"assistant"`:

```json
{
  "assistant": "gemini",
  ...
}
```

Valores: `"claude"` o `"gemini"`. Para cambiar la preferencia, edita el valor en `config.json`.

### Asistente local con Ollama

Instala [Ollama](https://ollama.com/) y descarga un modelo:

```bash
ollama pull llama3.2
claude_udea --ollama --skip-video
```

Puedes elegir otro modelo con `--ollama-model` o con `CLAUDE_UDEA_OLLAMA_MODEL`.
El chat incluye `/listado`, `/leer ruta.vtt`, `/buscar texto`, `/pendientes`, `/ensenar tema`, `/help` y `/salir`.
Ollama se conecta a `OLLAMA_HOST` o, por defecto, a `http://127.0.0.1:11434`.

### Preferir transcripciones de faster-whisper

```bash
claude_udea --always-whisper --skip-video
```

Descarga temporalmente los videos que hagan falta y genera una VTT local. Si Zoom también proporciona subtítulos, el programa pregunta si quieres conservar ambas versiones. Whisper queda en `transcripts/whisper/` y los originales en `transcripts/zoom/`. La opción se aplica a las asignaturas seleccionadas; puedes indicar slugs para limitarla. Las transcripciones de faster-whisper ya correctas (con al menos un segmento) se conservan y no se vuelven a procesar; las vacías se reintentan en la siguiente ejecución. Requiere `faster-whisper`, FFmpeg y ffprobe.

### Calidad de la transcripción (faster-whisper)

Los parámetros de faster-whisper son configurables por flags. Por defecto se busca **máxima calidad** en CPU (pensado para un equipo potente, p. ej. Intel i9 + 24 GB); baja el modelo para acelerar. La GPU Intel (Iris Xe) no la usa CTranslate2, así que se corre en CPU.

| Flag | Default | Descripción |
|------|---------|-------------|
| `--whisper-model` | `large-v3` | Modelo (`tiny`, `base`, `small`, `medium`, `large-v2`, `large-v3`). Más grande = más preciso y más lento |
| `--whisper-compute-type` | `int8_float32` | Cómputo de CTranslate2 (`int8`, `int8_float32`, `float32`; `float16` solo con GPU NVIDIA) |
| `--whisper-device` | `cpu` | `cpu` o `cuda` (NVIDIA) |
| `--whisper-cpu-threads` | `8` | Hilos de CPU |
| `--whisper-beam-size` | `5` | Anchura de búsqueda (mayor = más preciso, más lento) |
| `--whisper-language` | `es` | Idioma |
| `--whisper-initial-prompt` | (texto del curso) | Contexto para mejorar términos propios; vacío para desactivarlo |
| `--whisper-chunk-seconds` | `1200` | Segundos por bloque (acota RAM y permite reanudar) |
| `--whisper-no-conditioning` | desactivado | Desactiva `condition_on_previous_text` (evita bucles de repetición) |

Además, al transcribir se descarga el **mejor audio** disponible (no el video liviano), lo que mejora el resultado. Ejemplos:

```bash
# Máxima calidad (default)
claude_udea --always-whisper --skip-video

# Equilibrio rapidez/calidad
claude_udea --always-whisper --skip-video --whisper-model medium --whisper-beam-size 3

# Rápido en equipos modestos
claude_udea --always-whisper --skip-video --whisper-model small --whisper-compute-type int8

# Con GPU NVIDIA
claude_udea --always-whisper --skip-video --whisper-device cuda --whisper-compute-type float16 --whisper-model large-v3
```

Los mismos flags funcionan al usar `transcribe_missing.py` directamente (`python transcribe_missing.py --always-whisper --whisper-model medium ...`).

**Limitar a un curso o una clase.** El curso se indica con su slug (posicional en `claude_udea`, o con `--course` en `transcribe_missing.py`) y la clase con `--class` (número de clase, repetible):

```bash
# Solo un curso
claude_udea --always-whisper --skip-video modelos-y-simulacion-de-sistemas-ii

# Solo las clases 9 y 10 de un curso
claude_udea --always-whisper --skip-video modelos-y-simulacion-de-sistemas-ii --class 9 --class 10

# Equivalente con transcribe_missing.py
python transcribe_missing.py --always-whisper --course arquitectura-de-software --class 5
```

Para **reemplazar** transcripciones anteriores (por ejemplo, al cambiar de modelo), mueve a un respaldo los `.whisper.transcript.vtt` en `transcripts/whisper/` del curso y vuelve a ejecutar; las existentes correctas se conservan y solo se reprocesan las que faltan.

### Ejecutar sin asistente

```bash
claude_udea --no-assistant
```

Descarga y organiza las transcripciones sin exigir ni abrir Claude Code, Gemini CLI u Ollama. `--no-claude` se mantiene como alias compatible.

### Opciones

```bash
claude_udea --status          # Ver estado de descargas por asignatura
claude_udea --skip-scrape     # Solo descargar (sin re-scrapear Moodle)
claude_udea --skip-video      # Solo transcripciones (sin preguntar)
claude_udea --all             # Video + transcripciones (sin preguntar)
claude_udea --dry-run         # Simular sin descargar nada
claude_udea --add-course      # Agregar una nueva asignatura
claude_udea --no-assistant    # No abrir un asistente de IA
claude_udea --ollama          # Abrir chat local con Ollama
claude_udea --ollama --ollama-model mistral  # Elegir modelo local
claude_udea --no-claude       # Alias compatible de --no-assistant
claude_udea --sync-materials  # Solo materiales Moodle; no descarga grabaciones
claude_udea --skip-materials  # Omitir materiales en el flujo normal
claude_udea --sync-ingenia-materials "https://ingenia.udea.edu.co/campus/course/view.php?id=215"
claude_udea --always-whisper --skip-video # Crear VTT con faster-whisper
claude_udea --repair-videos --dry-run    # Previsualizar reparación de nombres y duplicados
claude_udea --repair-videos             # Reparar archivos del curso sin scrapear ni abrir asistente
```

En cada carpeta `downloads/<curso>/` los archivos se separan en `videos/`, `transcripts/zoom/` y `transcripts/whisper/`. Los archivos de chat de Zoom no se descargan: la plataforma no los expone de forma fiable para cada grabación.

### Reparar videos y transcripciones de Zoom

La numeración `Parte N` corresponde a una pieza de video distinta de una misma clase. Sus archivos `.cc.vtt`, `.transcript.vtt`, `.chapter.vtt` y `.whisper.transcript.vtt` conservan el mismo slot; los subtítulos no generan números de parte por separado. Si los metadatos guardan rutas antiguas, la fecha y la categoría del nombre canónico se usan para no atribuir archivos de otra clase.

```bash
# Revisar qué se movería, renombraría o pondría en cuarentena
claude_udea --repair-videos --dry-run arquitectura-de-software

# Aplicar la reparación de un curso (también acepta varios slugs)
claude_udea --repair-videos arquitectura-de-software
```

La reparación detecta nombres repetidos como `Parte 1 - Parte 1`, duplicados byte a byte, subtítulos Zoom copiados entre clases y grabaciones vacías. Los archivos retirados se conservan en `.claude-udea-backup/<motivo>/` junto con un `manifest.jsonl`; los movimientos se registran también en `repair-manifest.jsonl`. La reasignación entre clases requiere una fecha interna verificable con ffprobe. Si un video se reasigna, sus subtítulos antiguos se respaldan: compartir un número de parte no prueba que pertenezcan al video. Los subtítulos Zoom retirados se vuelven a solicitar sin descargar de nuevo el video. Los clips cortos válidos se conservan y se reportan, en vez de clasificarse automáticamente como vacíos. La misma revisión preventiva también ocurre al final del flujo normal.

La vista previa no mueve archivos ni actualiza `recordings.json`. Antes de aplicar `--repair-videos`, el comando guarda una copia fechada de `recordings.json`; los cursos no seleccionados no se reorganizan ni se sobrescriben en el índice central. El reporte no reasigna contenido ambiguo: deja videos para revisión y respalda subtítulos cuya relación con el video no puede comprobarse. Se recomienda revisar el reporte antes de aplicar y conservar las carpetas de respaldo hasta verificar los nombres y contenidos.

El comando de Ingenia solicita usuario y contraseña directamente en la terminal si no existe una sesión válida. Los datos se guardan separados de Moodle en Windows Credential Manager. La cuenta debe estar matriculada en el curso; el scraper no intenta comprar ni matricularse.

### Filtrar por asignatura

```bash
claude_udea calidad-de-software          # Solo una asignatura
claude_udea ingenieria-web optimizacion  # Varias especificas
```

---

## Skills de Claude Code

Una vez dentro de Claude Code, tenes comandos especializados:

| Comando | Que hace |
|---------|----------|
| `/ensenar [tema]` | Ensena un tema visto en clase con referencias a la grabacion y minuto |
| `/pendientes` | Lista todos los compromisos: parciales, tareas, quices, entregas |
| `/planear` | Ayuda a organizar tu tiempo y crear horarios de estudio |
| `/buscar [termino]` | Busca una palabra o frase en todas las transcripciones |
| `/temas` | Muestra todos los temas vistos, organizados cronologicamente |
| `/ejemplos [tema]` | Da ejemplos practicos sobre un tema de clase |
| `/taller` | Ayuda a resolver un taller con base en lo visto en clase |

### Ejemplo de uso

```
> /pendientes

Compromisos encontrados:

  Parcial 2 - Calidad de Software
    2026-03-25 | calidad-clase-15.vtt | ~min 45
    "El parcial va a ser sobre testing y metricas"

  Entrega Taller 3 - Ingenieria Web
    2026-03-28 | ingenieria-clase-12.vtt | ~min 32
    "El taller es en grupos de 3, entrega por Moodle"
```

---

## Archivos y nombres

```
~/claude-udea/                    # macOS/Linux
C:\claude-udea\                   # Windows
|-- CLAUDE.md                     # Instrucciones para Claude Code (auto-generado)
|-- config.json                   # Tus asignaturas configuradas
|-- recordings.json               # Registro de grabaciones encontradas
|-- course-materials/             # Documentos y páginas de Moodle
|   |-- arquitectura-de-software/
|   |   |-- manifest.json         # Origen, tamaño, hash y estado de archivos
|   |   +-- files/                 # Documentos descargados
|   +-- ...
|-- .claude/
|   |-- rules.md                  # Reglas del asistente
|   +-- skills/                   # Comandos disponibles
|       |-- ensenar.md
|       |-- pendientes.md
|       |-- planear.md
|       |-- buscar.md
|       |-- temas.md
|       |-- ejemplos.md
|       +-- taller.md
+-- downloads/
    |-- calidad-de-software/      # Archivos descargados por asignatura
    |   |-- videos/               # Videos organizados por clase y parte
    |   |-- transcripts/
    |   |   |-- zoom/             # .cc.vtt, .transcript.vtt y .chapter.vtt
    |   |   +-- whisper/          # Una transcripción por cada slot de video
    |   +-- .claude-udea-backup/  # Duplicados, huérfanos y archivos dudosos
    |       |-- identical-videos/
    |       |-- misassigned-videos/
    |       |-- misassigned-transcripts/
    |       +-- empty-videos/
    |-- ingenieria-web/
    +-- transcripts/              # Transcripciones organizadas
        |-- index.json            # Indice por fecha y asignatura
        |-- calidad-de-software/
        |   |-- Clase #1 - 2026-03-09.transcript.vtt
        |   +-- Clase #2 - 2026-03-12.transcript.vtt
        +-- ingenieria-web/
            +-- ...
```

Las credenciales y cookies no se guardan como archivos en claro: se almacenan en el almacén seguro del sistema operativo. Los nombres de grabaciones incluyen número y fecha; Arquitectura de Software y Fábrica Escuela mantienen secuencias independientes. `downloads/transcripts/index.json` contiene metadata por asignatura, incluyendo el número de parte.

Cuando el organizador encuentra videos idénticos (mismo tamaño y hash SHA-256), mueve las copias a `downloads/<curso>/.claude-udea-backup/identical-videos/` y registra origen, destino y hash en un `manifest.jsonl`, en vez de borrarlas. Los videos de una misma sesión con contenido distinto se conservan como `Clase #N - fecha - Parte M.mp4`. Las transcripciones Zoom y Whisper usan ese mismo slot; una transcripción no crea su propia parte. Los nombres anidados heredados se normalizan desde la base canónica, por ejemplo `Clase #15 - 2026-09-29 - Parte 1 - Parte 1.mp4` deja de acumular sufijos.

  ## Transcribir grabaciones sin subtítulos

  `transcribe_missing.py` genera transcripciones locales con faster-whisper para cada video o parte que aún no tenga su propio `.whisper.transcript.vtt`. Procesa el audio por bloques, permite reanudar cada slot interrumpido y actualiza `downloads/transcripts/` y su índice. Un Whisper de la parte 2 no cuenta como transcripción del video principal ni de la parte 1.

  Instala faster-whisper y FFmpeg (incluido ffprobe), y lista las grabaciones pendientes:

  ```bash
  pip install faster-whisper
  python transcribe_missing.py --work-dir /ruta/a/claude-udea --check
  ```

  Para procesar solo las partes sin subtítulos Zoom se puede usar `--only-missing`; `--check` lista cada slot pendiente sin cargar el modelo. El directorio predeterminado depende del sistema (en Windows, `C:\\claude-udea`); también se puede indicar con `--work-dir`.

  ## Materiales Moodle

  Los materiales quedan en `course-materials/<curso>/`, fuera de `downloads/`, para que el organizador de videos y transcripciones no los renombre. El scraper sigue las secciones `section=...` enlazadas por Moodle y recoge archivos directos, carpetas, recursos, el texto y adjuntos de actividades Página, y adjuntos de instrucciones docentes de tareas. Las entregas de estudiantes se excluyen. Las actividades `URL` externas se registran en `manifest.json`, pero no se descargan desde dominios externos.

  La sincronización de materiales soporta Moodle e Ingenia. La ruta Ingenia `/campus/course/view.php` puede llevar a la página de matrícula/compra en vez del aula; para sincronizar materiales se requiere una cuenta autorizada y matrícula activa. El acceso usa credenciales independientes de Moodle UdeArroba.

---

## Como funciona

```
+-----------+     +-----------+     +-----------+     +----------------+
| Moodle /  |---->| Scraping  |---->| Descarga  |---->| Claude/Gemini/ |
| Ingenia   |     | (requests)|     | (yt-dlp)  |     | Ollama o solo |
+-----------+     +-----------+     +-----------+     | transcripciones|
  |                 |                  |           +----------------+
 Login Moodle    Busca links       Videos y VTTs       Chat opcional
 si aplica       en paralelo       en paralelo         o modo sin IA
```

1. **Login**: POST directo con usuario y contraseña, sin navegador. La sesión y las credenciales para re-login se guardan localmente.
2. **Scraping**: Moodle e Ingenia se recorren por sus secciones autenticadas para encontrar documentos, páginas y carpetas. Las listas de grabaciones Zoom se obtienen desde las páginas de cada plataforma; en Moodle se aplica el filtro por rango de fechas (ventanas de 30 días) y se siguen los enlaces de paginación de la misma actividad, para no perder grabaciones antiguas ni las de listados que ocupan varias páginas.
3. **Descarga**: yt-dlp descarga transcripciones (`.vtt`) y, si se solicita, videos. El pipeline descarga en paralelo y añade metadata a los VTT. Antes de omitir una grabación se comprueba que el video exista en disco; los videos faltantes se vuelven a descargar aunque el archive los marcara como ya procesados, sin re-descargar los subtítulos ya existentes.
4. **Organización**: se asigna numeración secuencial independiente a Arquitectura de Software y Fábrica Escuela, se regenera el índice por asignatura y se deduplican por contenido (SHA-256) los videos idénticos, respaldándolos sin borrarlos y conservando las partes reales con el sufijo ` - Parte N`. Los subtítulos sueltos se mueven a `transcripts/zoom/` o `transcripts/whisper/`.
5. **Asistente**: Claude Code y Gemini CLI usan las instrucciones generadas. Ollama ofrece un chat local con acceso al índice y a los VTT que se carguen con `/leer`.
6. **Material Moodle**: los archivos se descargan en `course-materials/` con manifiestos de origen, tamaño y hash. Las entregas de estudiantes no se recopilan.

---

## Privacidad y seguridad

- Las cookies y credenciales Moodle e Ingenia se guardan por separado en el almacén seguro del sistema operativo (`Windows Credential Manager` en Windows). No se mantienen en JSON en claro.
- Al migrar una instalación previa, los JSON legados solo se eliminan después de verificar que su contenido quedó guardado en el almacén seguro.
- Si el sistema no ofrece un backend de keyring seguro, el programa falla de forma cerrada y no vuelve a guardar secretos sin cifrar.
- Las descargas y transcripciones se guardan localmente. El scraping consulta Moodle, Ingenia y Zoom.
- Ollama se conecta al servidor configurado en `OLLAMA_HOST` (local por defecto). Claude Code y Gemini CLI son servicios de terceros; revisa sus políticas antes de enviar contenido de clase.

---

## Solucion de problemas

### "claude/gemini no esta en el PATH"
```bash
# Si elegiste Claude Code:
npm install -g @anthropic-ai/claude-code

# Si elegiste Gemini CLI:
npm install -g @google/gemini-cli
```

### "Ollama no responde" o no encuentra el modelo

Inicia Ollama, descarga un modelo (por ejemplo `ollama pull llama3.2`) y vuelve a ejecutar `claude_udea --ollama`. Si usas otro servidor, configura `OLLAMA_HOST`.

### "No hay transcripciones pendientes" con faster-whisper

Confirma que el directorio pasado con `--work-dir` contenga `recordings.json` y `downloads/`. Para transcribir, instala `faster-whisper` y asegúrate de que `ffmpeg` y `ffprobe` estén en el `PATH`.

### "externally-managed-environment" al instalar con pip
Usa un entorno virtual (ver seccion de instalacion arriba).

### "La sesion de Moodle siempre expira"
Es normal que expire despues de varias horas. Al ejecutar `claude_udea` de nuevo, te pedira credenciales solo si es necesario.

### "Se descargan grabaciones duplicadas"

El organizador deduplica los videos por contenido (SHA-256) y respalda las copias idénticas en `downloads/<curso>/.claude-udea-backup/identical-videos/`, sin borrarlas. Los videos de una misma sesión con contenido distinto se conservan con el sufijo ` - Parte N`.

Si tenes archivos viejos con nombres tipo `[rec_id]` o `[rec_id copy N]`, una ejecución normal (`claude_udea --no-assistant <curso>`) los renombra a la convención `Clase #N - fecha` y actualiza `recordings.json`.

### Resetear todo
```bash
# Windows
rmdir /s /q C:\claude-udea\downloads
del C:\claude-udea\recordings.json C:\claude-udea\.moodle-session.json

# macOS/Linux
rm -rf ~/claude-udea/downloads
rm ~/claude-udea/recordings.json ~/claude-udea/.moodle-session.json
```

---

## Pruebas

```bash
python -m unittest discover -s tests -v
```

## Licencia

MIT

---

<p align="center">
  Hecho para estudiantes de la <strong>Universidad de Antioquia</strong>
</p>
