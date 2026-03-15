---
name: taller
description: Ayuda a resolver un taller o trabajo usando exclusivamente lo visto en clase hasta la fecha del taller.
user_invocable: true
---

# /taller

El estudiante tiene un taller, trabajo o tarea y necesita ayuda para resolverlo.

## Instrucciones

1. Pide al estudiante que comparta el enunciado del taller (puede pegar texto, compartir un archivo, o describir los puntos).

2. Identifica la asignatura y la fecha del taller.

3. **IMPORTANTE**: Solo usa conocimiento de las transcripciones de clases hasta la fecha del taller, NO de clases posteriores. El taller evalúa lo visto hasta ese momento.

4. Para cada punto del taller:

```
### Punto [N]

**Tema relacionado:** [tema visto en clase]
**Visto en:** [archivo.vtt | ~min XX]

**Respuesta/Solución:**
[Solución basada en lo visto en clase]

**Justificación desde la clase:**
[Qué dijo el profesor que sustenta esta respuesta]
```

5. Si un punto requiere conocimiento que NO se vio en las transcripciones:
   - Dilo explícitamente: "Este punto parece requerir [tema] que no encontré en las transcripciones disponibles."
   - Ofrece orientación general pero aclara que no viene de la clase.

6. Si el taller tiene puntos de código:
   - Escribe código funcional
   - Comenta las partes que se relacionan con lo visto en clase
   - Sigue el estilo o herramientas que usó el profesor

7. Al final, ofrece: "¿Querés que repase contigo los temas que cubre este taller? Usá /enseñar [tema]"
