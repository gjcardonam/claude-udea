---
name: planear
description: Ayuda al estudiante a organizar su tiempo, crear horarios de estudio, y planificar cómo cumplir con todos sus compromisos académicos.
user_invocable: true
---

# /planear

El estudiante necesita ayuda para organizar su tiempo y planificar sus actividades académicas.

## Instrucciones

1. Primero ejecuta internamente lo que haría `/pendientes`: busca TODOS los compromisos en las transcripciones.

2. Pregunta al estudiante (si no lo ha dicho):
   - "¿Qué días y horas tenés disponibles para estudiar esta semana?"
   - "¿Hay algo que ya tengas avanzado?"

3. Crea un plan organizado:

```
## 📅 Plan de estudio

### Esta semana (Lun-Dom)

| Día | Horario | Actividad | Asignatura |
|-----|---------|-----------|-----------|
| Lunes | 14:00–16:00 | Estudiar [tema] para quiz | Calidad |
| Martes | 10:00–12:00 | Resolver taller 2 | Optimización |
| ... | ... | ... | ... |

### Prioridades
1. 🔴 **Urgente**: [tarea que vence pronto]
2. 🟡 **Esta semana**: [siguiente entrega]
3. 🟢 **Puede esperar**: [entrega lejana]

### Recomendaciones
- Para el parcial de [X], repasá: [temas, con referencia a clases]
- El taller de [Y] cubre: [temas], dedicale al menos [N] horas
```

4. Sé realista con los tiempos:
   - Parcial: mínimo 4-6 horas de preparación
   - Taller: depende de la complejidad, 2-4 horas
   - Quiz: 1-2 horas de repaso
   - Lectura/repaso: 1 hora por clase

5. Distribuye la carga: no todo el mismo día. Alterna materias.

6. Si hay conflictos (mucho en poco tiempo), señálalo y sugiere qué priorizar.

7. Ofrece: "¿Querés que te ayude a estudiar alguno de estos temas? Usá /enseñar [tema]"
