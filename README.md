<p align="center">
  <h1 align="center">claude_udea</h1>
  <p align="center">
    <strong>Tu asistente academico con IA para la Universidad de Antioquia</strong>
  </p>
  <p align="center">
    Descarga automatica de transcripciones de Zoom desde Moodle -> Analisis con Claude Code
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-≥3.10-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/Claude_Code-CLI-orange?style=flat-square&logo=anthropic&logoColor=white" alt="Claude Code">
    <img src="https://img.shields.io/badge/plataforma-Windows_|_macOS_|_Linux-green?style=flat-square" alt="Cross-platform">
  </p>
</p>

---

## Que es?

`claude_udea` es una herramienta de linea de comandos que:

1. **Scrapea** las grabaciones de Zoom desde Moodle (UdeArroba)
2. **Descarga** las transcripciones (y opcionalmente los videos)
3. **Abre Claude Code** como asistente academico personalizado con tus clases

Todo en un solo comando: `claude_udea`

---

## Caracteristicas

- **Sin navegador** -- login y scraping por HTTP directo, no necesita GUI ni Chromium
- **Pipeline paralelo** -- scrapea materias y descarga grabaciones simultaneamente
- **Setup interactivo** -- la primera vez te guia para configurar tus asignaturas
- **Instalacion automatica** -- detecta e instala dependencias faltantes (incluido Claude Code)
- **Sesion persistente** -- guarda tu sesion de Moodle para no pedir login cada vez
- **Descarga incremental** -- nunca re-descarga lo que ya tenes
- **Deduplicacion inteligente** -- identifica grabaciones por fecha, sin duplicados
- **Cross-platform** -- funciona en Windows, macOS y Linux (incluido Raspberry Pi headless)
- **Skills de Claude** -- comandos especializados para estudiar con IA

---

## Requisitos previos

| Requisito | Para que | Como instalar |
|-----------|----------|---------------|
| **Python >= 3.10** | Ejecutar la herramienta | [python.org](https://www.python.org/downloads/) |
| **Node.js >= 18** | Instalar el asistente AI | [nodejs.org](https://nodejs.org/) (LTS) |
| **Git** | Clonar el repositorio | [git-scm.com](https://git-scm.com/) |

> Las demas dependencias (yt-dlp, requests, etc.) se instalan automaticamente.

### Asistente AI

La primera vez que ejecutes `claude_udea`, te preguntara que asistente queres usar:

| Asistente | Costo | Limite |
|-----------|-------|--------|
| **Gemini CLI** (Google) | Gratis | 1000 requests/dia con cuenta Google |
| **Claude Code** (Anthropic) | $20/mes (Pro) | Mejor calidad de respuestas |

Podes cambiar de asistente despues editando `assistant` en `~/claude-udea/config.json`.

---

## Instalacion

### Opcion 1: Desde GitHub (recomendado)

```bash
pip install git+https://github.com/gjcardonam/claude-udea.git
```

### Opcion 2: Clonar y desarrollo local

```bash
git clone https://github.com/gjcardonam/claude-udea.git
cd claude-udea
pip install -e .
```

### Nota para sistemas con Python externally-managed (Ubuntu 23+, Raspberry Pi OS, Fedora 38+)

Si ves el error `externally-managed-environment`, usa un entorno virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
pip install git+https://github.com/gjcardonam/claude-udea.git
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

> **Antes de empezar**: tene listos los links de la pagina de grabaciones de cada asignatura en Moodle.
> Es la pagina donde ves la lista de grabaciones de Zoom con los botones "Ver grabacion".
> Solo se piden **una vez** durante la configuracion inicial.

#### Como conseguir el link?

1. Entra a [UdeArroba](https://udearroba.udea.edu.co/)
2. Abri la asignatura
3. Busca la actividad de **Zoom** donde estan las grabaciones
4. Copia la URL de esa pagina -- es algo como `https://udearroba.udea.edu.co/mod/zoom/view.php?id=XXXXX`

#### Ejecutar

```bash
claude_udea
```

Se va a:

1. Verificar e instalar dependencias faltantes
2. Preguntar que asistente AI queres (Gemini gratis o Claude de pago)
3. Pedir los links de grabaciones de cada asignatura (solo la primera vez)
4. Pedir usuario y contrasena de Moodle en la terminal (sin navegador)
5. Scrapear y descargar todo en paralelo
6. Abrir el asistente AI con tus transcripciones

### Ejecuciones siguientes

```bash
claude_udea              # Actualiza todo y abre Claude Code
```

Si tu sesion de Moodle sigue activa, no pide credenciales -- todo corre automaticamente.

### Cambiar de asistente

Edita `~/claude-udea/config.json` (o `C:\claude-udea\config.json` en Windows) y cambia `"assistant"`:

```json
{
  "assistant": "gemini",
  ...
}
```

Valores: `"claude"` o `"gemini"`.

### Opciones

```bash
claude_udea --status          # Ver estado de descargas por asignatura
claude_udea --skip-scrape     # Solo descargar (sin re-scrapear Moodle)
claude_udea --skip-video      # Solo transcripciones (sin preguntar)
claude_udea --all             # Video + transcripciones (sin preguntar)
claude_udea --dry-run         # Simular sin descargar nada
claude_udea --add-course      # Agregar una nueva asignatura
```

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

## Estructura de archivos

```
~/claude-udea/                    # macOS/Linux
C:\claude-udea\                   # Windows
|-- CLAUDE.md                     # Instrucciones para Claude Code (auto-generado)
|-- config.json                   # Tus asignaturas configuradas
|-- recordings.json               # Registro de grabaciones encontradas
|-- .moodle-session.json          # Sesion de Moodle (cookies)
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
    |-- ingenieria-web/
    +-- transcripts/              # Transcripciones organizadas
        |-- index.json            # Indice por fecha y asignatura
        |-- calidad-de-software/
        |   |-- 2026-03-09_Clase 15 [...].vtt
        |   +-- 2026-03-12_Clase 16 [...].vtt
        +-- ingenieria-web/
            +-- ...
```

---

## Como funciona

```
+-----------+     +-----------+     +-----------+     +----------------+
|  Moodle   |---->| Scraping  |---->| Descarga  |---->| Claude / Gemini|
| (UdeArroba)|    | (requests)|     | (yt-dlp)  |     |  (Asistente)   |
+-----------+     +-----------+     +-----------+     +----------------+
     |                 |                  |                  |
  Login HTTP      Busca links        Baja VTTs        Lee transcripciones
  (una vez)      en paralelo       en paralelo        y responde preguntas
```

1. **Login**: POST directo con usuario/contrasena, sin navegador. La sesion se guarda localmente.
2. **Scraping**: requests + BeautifulSoup scrapean las tablas de grabaciones de cada materia en paralelo.
3. **Descarga**: yt-dlp descarga transcripciones (`.vtt`) en paralelo. Las descargas empiezan a medida que cada scrape termina (pipeline). Cada VTT se enriquece con metadata (fecha, asignatura, duracion).
4. **Asistente AI**: Se abre Claude Code o Gemini CLI (segun tu eleccion) con instrucciones personalizadas (`CLAUDE.md` / `GEMINI.md`) que le dicen que asignaturas tenes, donde estan las transcripciones, y como responder.

---

## Privacidad y seguridad

- Tus credenciales se piden por terminal y **solo se usan para hacer login** -- no se guardan en disco
- Las cookies de sesion se guardan localmente en `.moodle-session.json`
- Todo se procesa localmente en tu maquina
- Las transcripciones nunca se suben a ningun servidor externo
- Claude Code lee los archivos locales directamente

---

## Solucion de problemas

### "claude/gemini no esta en el PATH"
```bash
# Si elegiste Claude Code:
npm install -g @anthropic-ai/claude-code

# Si elegiste Gemini CLI:
npm install -g @google/gemini-cli
```

### "externally-managed-environment" al instalar con pip
Usa un entorno virtual (ver seccion de instalacion arriba).

### "La sesion de Moodle siempre expira"
Es normal que expire despues de varias horas. Al ejecutar `claude_udea` de nuevo, te pedira credenciales solo si es necesario.

### "Se descargan grabaciones duplicadas"
Esto se corrigio automaticamente. Si tenes datos viejos, borra `recordings.json` y ejecuta de nuevo:
```bash
# Windows
del C:\claude-udea\recordings.json

# macOS/Linux
rm ~/claude-udea/recordings.json
```

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

## Licencia

MIT

---

<p align="center">
  Hecho para estudiantes de la <strong>Universidad de Antioquia</strong>
</p>
