---
name: temas
description: Muestra todos los temas vistos en una o todas las asignaturas, organizados cronológicamente con referencias a las grabaciones.
user_invocable: true
---

# /temas

El estudiante quiere ver qué temas se han visto en clase.

## Instrucciones

1. Si el estudiante especificó una asignatura (ej: `/temas calidad`), lee TODAS las transcripciones `.transcript.vtt` de esa asignatura. Si no especificó, pregunta cuál.

2. Lee cada archivo de la asignatura. Extrae los temas principales que se trataron en cada clase.

3. Presenta los temas así:

```
## [Nombre de la asignatura]

### Clase 1 — [fecha si se menciona]
📄 archivo.vtt

- **Tema 1**: Descripción breve de qué se vio
- **Tema 2**: Descripción breve

### Clase 2 — [fecha]
📄 archivo.vtt

- **Tema 3**: ...
```

4. No omitas NINGÚN tema. Todo lo que se vio debe aparecer.

5. Al final, muestra un resumen tipo índice:

```
### Índice de temas
1. Tema X — Clase 1, ~min 5
2. Tema Y — Clase 1, ~min 23
3. Tema Z — Clase 2, ~min 8
```

6. No des explicaciones de los temas, solo lista qué se vio. Si el estudiante quiere aprender un tema, debe usar `/enseñar`.
