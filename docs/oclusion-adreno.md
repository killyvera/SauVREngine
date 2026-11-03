# Oclusión por hardware en Adreno (Quest 3)

## Estado actual

- La oclusión está apagada en Android: `oqfrags 0` y `doOQ = false` en `renderva.cpp`.
  Motivo documentado en el código: un `GL_INVALID_ENUM` durante el pase de geometría, y la
  geometría lejana desaparecía.
- Con la oclusión apagada, el mundo se dibuja entero dentro del PVS y del frustum. Es el
  coste que tenemos en vistas densas.

## Causa probable del error (confirmada por la especificación)

- El código usa `glBeginQuery(GL_SAMPLES_PASSED, …)` (`renderva.cpp`, `startquery`/`endquery`).
- En OpenGL ES 3.x, `glBeginQuery` solo acepta `GL_ANY_SAMPLES_PASSED`,
  `GL_ANY_SAMPLES_PASSED_CONSERVATIVE`, `GL_PRIMITIVES_GENERATED` o
  `GL_TRANSFORM_FEEDBACK_PRIMITIVES_WRITTEN`. `GL_SAMPLES_PASSED` es solo de escritorio.
  Fuente: [glBeginQuery, referencia ES 3](https://registry.khronos.org/OpenGL-Refpages/es3/html/glBeginQuery.xhtml).
- Eso encaja con el `GL_INVALID_ENUM` observado: la consulta nunca se ejecuta, su resultado
  queda en 0 y el motor la toma por oculta. Por eso desaparecía la geometría lejana.

## Cambio de lógica que implica

- `GL_ANY_SAMPLES_PASSED` devuelve 0 o 1, no un conteo de fragmentos. La comparación actual
  `fragments < oqfrags` (con `oqfrags = 8`) daría "oculto" para cualquier cosa visible.
  Con booleano, oculto es `fragments == 0`.
- `GL_ANY_SAMPLES_PASSED_CONSERVATIVE` puede dar falsos positivos (dibujar algo oculto), pero
  nunca marca como oculto algo visible. Es el más seguro para no perder geometría.
  Se usa este.

## Plan de prueba

1. Cambiar el target a `GL_ANY_SAMPLES_PASSED_CONSERVATIVE` y la comparación a `fragments == 0`.
2. Quitar el bloqueo de Android (`oqfrags` máximo 0 y `doOQ = false`).
3. Medir en ruebli, preset rendimiento, con la misma línea base (`4168f81`):
   `draw`, `lotes`, `gpu`, `fps`, `p95`.
4. Revisar visualmente que no desaparezca geometría lejana ni bots, y que `glerr` y `e502`
   sigan en 0.
5. Si algo falla, `oqfrags 0` desde consola lo apaga sin recompilar.

## Riesgos

- Con conservador, las consultas pueden no ahorrar tanto como un conteo exacto.
- En multiview, una consulta cubre las dos vistas a la vez. Con conservador, si un objeto se
  ve en un ojo, la consulta es "visible", que es el resultado seguro.
- La consulta espera al resultado de un frame anterior (`oqwait`). Puede aumentar latencia
  si el resultado llega tarde.

## Criterio de decisión

Se conserva si baja `draw` y `lotes` en vistas densas sin perder geometría ni bots, y si
`fps` y `p95` no empeoran. Si no baja `draw`, se apaga y se documenta.
