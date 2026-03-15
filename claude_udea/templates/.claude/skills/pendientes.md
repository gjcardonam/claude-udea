---
name: pendientes
description: Busca y presenta todos los compromisos, tareas, parciales, quices y entregas mencionados en las transcripciones de clase.
user_invocable: true
---

# /pendientes

El estudiante quiere ver todos sus compromisos académicos.

## Instrucciones

1. Lee TODAS las transcripciones `.transcript.vtt` de TODAS las asignaturas.

2. Busca menciones de:
   - Parciales, exámenes, evaluaciones
   - Quices, quiz
   - Tareas, trabajos
   - Talleres
   - Entregas, proyectos
   - Exposiciones, presentaciones
   - Cualquier frase como: "para la próxima", "tienen que entregar", "la fecha es", "deben hacer", "el parcial es", "recuerden que", "no se les olvide", "deadline", "fecha límite"

3. Presenta los resultados así:

```
## 📋 Pendientes académicos

### ⚠️ Próximos / Urgentes
| Qué | Asignatura | Fecha | Fuente |
|-----|-----------|-------|--------|
| Parcial 1 | Calidad de Software | 2026-03-20 | [archivo.vtt ~min 45] |
| Taller 2 | Optimización | 2026-03-18 | [archivo.vtt ~min 12] |

### 📅 Más adelante
| Qué | Asignatura | Fecha | Fuente |
|-----|-----------|-------|--------|
| Proyecto final | Ing. Web | 2026-05-15 | [archivo.vtt ~min 30] |

### ✅ Posiblemente vencidos (fecha anterior a hoy)
| Qué | Asignatura | Fecha | Fuente |
|-----|-----------|-------|--------|
| Quiz 1 | Seguridad | 2026-03-10 | [archivo.vtt ~min 8] |
```

4. Ordena por fecha, los más próximos primero.

5. Si no se mencionó una fecha exacta, pon "Sin fecha exacta" y cita lo que dijo el profesor.

6. Si el estudiante pide `/pendientes calidad`, filtra solo esa asignatura.

7. Al final: "¿Querés que te ayude a planear cómo abordar estos pendientes? Usá /planear"
