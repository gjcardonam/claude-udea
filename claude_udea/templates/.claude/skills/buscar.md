---
name: buscar
description: Busca una palabra, frase o tema específico en todas las transcripciones y muestra exactamente dónde se mencionó con timestamps.
user_invocable: true
---

# /buscar [término]

El estudiante quiere encontrar dónde se habló de algo específico.

## Instrucciones

1. Usa la herramienta Grep para buscar el término en todos los archivos `.vtt` dentro de `downloads/transcripts/`.

2. Si el término es muy específico y no da resultados, intenta variaciones (singular/plural, con/sin tilde, sinónimos comunes).

3. Presenta los resultados así:

```
## 🔍 Resultados para "[término]"

### Calidad de Software
- **archivo.vtt** | ~min 12: "...contexto donde se menciona..."
- **archivo.vtt** | ~min 45: "...otra mención..."

### Ingeniería Web
- **archivo.vtt** | ~min 8: "...contexto..."

> Se encontraron X menciones en Y grabaciones.
```

4. Muestra contexto: la línea donde aparece y las líneas adyacentes para que tenga sentido.

5. Convierte el timestamp del VTT (00:12:34) a minutos legibles (~min 12).

6. Si no se encuentra nada: "No encontré menciones de '[término]' en las transcripciones. ¿Querés que busque algo relacionado?"
