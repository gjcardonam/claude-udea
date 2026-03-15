---
name: enseñar
description: Enseña un tema específico visto en clase de forma completa, profesional y al grano, basándose exclusivamente en las transcripciones.
user_invocable: true
---

# /enseñar [tema]

El estudiante quiere aprender un tema específico visto en clase.

## Instrucciones

1. Busca el tema en TODAS las transcripciones `.transcript.vtt` de la asignatura relevante (o todas si no se especifica).

2. Recopila TODO lo que el profesor dijo sobre ese tema. No omitas nada.

3. Organiza la enseñanza así:

```
## [Tema]

**Visto en:** [Asignatura | archivo.vtt | ~min XX]

### Concepto
[Explicación clara y directa del tema tal como se vio en clase]

### Puntos clave
- Punto 1
- Punto 2
- ...

### Lo que enfatizó el profesor
[Cosas que el profesor repitió, marcó como importantes, o dijo "esto es clave/importante/va en el parcial"]
```

4. Sé fiel a lo que dijo el profesor. Si usó una analogía o ejemplo en clase, inclúyelo.

5. NO agregues información externa. Solo lo que está en las transcripciones.

6. NO des ejemplos de código o ejercicios a menos que el profesor los haya dado en clase o que el estudiante los pida con `/ejemplos`.

7. Si el tema se vio en múltiples clases, unifica todo pero indica de qué clase viene cada parte.

8. Al final: "¿Querés que profundice en algún punto o que te dé ejemplos prácticos? Usá /ejemplos [tema]"
