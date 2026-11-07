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

## Resultado de la prueba A/B (ruebli, preset rendimiento, con 8 bots)

- Con oclusión encendida (`2f41d69`): la línea horizontal marcada aparece en las capturas.
  Telemetría: `draw` 408, `lotes` 347, `fps` 63,9, `gpu` 10,2 ms.
- Con oclusión apagada (`804c29f`, `oqfrags 0` por defecto): **la línea desaparece** (confirmado
  en el visor). Telemetría: `draw` 1421, `lotes` 1204, `fps` 58,4, `gpu` 11,6 ms. Ojo: esta
  sesión mezcla sombra real apagada y encendida (18 y 18 líneas), así que el fps no es
  comparable directamente con la línea base.
- Conclusión: la oclusión baja muchos draw calls (408 frente a 1421), pero el resultado en
  pantalla es incorrecto: una parte del mundo se dibuja con otro estado de sombra. Hasta
  corregirlo, se mantiene **apagada en Android**.
- Los errores `GL_INVALID_OPERATION` (`gllast=502`) ya aparecían antes de este cambio
  (línea base `4168f81`), así que no son de la consulta nueva.

## Diagnóstico de las líneas (build 686a1b6, 2026-11-04/05)

Cambios en esta ronda, todos en `src/engine/renderva.cpp`:

1. `enablevquery` fuerza siempre `glColorMask(false)` y `glDepthMask(false)` antes del pase de
   consultas, en vez de confiar en `cur`. Hipótesis: el estado de GL estaba desincronizado de
   `cur`. **Resultado: las líneas siguen.** Descarta esa causa sola.
2. Nuevo interruptor `oqdraw` (`VAR(oqdraw, 0, 0, 1)`, por defecto 0 en esta build): abre y cierra
   la consulta sin dibujar la caja. Con `oqskip 0` los VAs ocultos se siguen dibujando, así que
   la imagen debe quedar completa. Si las líneas desaparecen, la causa son las cajas de consulta.
   **Resultado: pendiente de confirmar.** Build 0228 instalada por ADB.

Lo que la telemetría dice y lo que no:
- Build 0228 (02:29 UTC): aún no hay telemetría de esta build con `oqdraw 0` en ruebli.
- Telemetría anterior (build 686a1b6, ruebli): 70–71 fps, `draw` 337, `lotes` 292, `glerr` 0.
- La telemetría no registra `oqdraw`, así que no sirve para confirmar el valor en la prueba.

## Resultado: oqdraw 0 (build 0228, ruebli)

- **Las líneas siguen con `oqdraw 0`.** Dibujar las cajas de consulta no es la causa.
- Esta prueba no es completamente limpia: con `oqdraw 0` todas las consultas devuelven 0 muestras,
  así que todos los VAs quedan marcados como ocultos. Con `oqskip 0` se siguen dibujando, pero otros
  caminos (`oqrecover`, el segundo bucle del pase Z) sí dependen de ese estado. Hay que tenerlo en
  cuenta al leer el resultado.
- Lo que queda como causa: el estado que dejan `startbb`/`endbb` (VBO/EBO, punteros de vértice,
  shader `bbquery`), las propias `glBeginQuery`/`glEndQuery` o la lectura de resultados en `checkquery`.
- Los logs de esta prueba están en `logcat_oqdraw.txt` (completo) y `logcat_filtro_oqdraw0.txt` (solo
  SauerQuest y errores). No hay errores de GL durante la partida; solo avisos informativos de GLDEBUG.

## Prueba oqnoquery (build 0242)

- Nuevo interruptor `oqnoquery` (por defecto 1 en esta build): no emite `glBeginQuery`/`glEndQuery`, ni
  `startbb`/`endbb`, ni dibuja cajas, y `checkquery` devuelve "oculto" sin tocar GL. La decisión de
  ocultar es la misma que con `oqdraw 0`; lo que cambia es que GL no recibe ninguna orden de consulta.
- Lectura: si las líneas desaparecen, la causa está en el estado GL de las consultas o del bbox
  (`startbb`/`endbb`, `glBeginQuery`/`glEndQuery`, o la lectura en `checkquery`). Si siguen, la
  causa está en el resto del pase con la decisión "todo oculto" (`oqrecover`, pase Z) o fuera de las consultas.
- Resultado: pendiente de la prueba en el visor.

### Resultado de oqnoquery (build 0242) y siguiente paso

- **Las líneas siguen** sin ninguna consulta GL ni estado del bbox. Esa parte queda descartada.
- Con todo marcado como oculto, desaparecen los jugadores: `rendermodel.cpp` (`modeloccluded` →
  `bboccluded`) salta los modelos dentro de VAs con `occluded >= OCCLUDE_BB`. Es un efecto de la
  prueba, no del glitch.
- Build 0251: `checkquery` devuelve "visible" con `oqnoquery`, así que la oclusión viene solo de la PVS
  pero el camino `doOQ` (pase Z con `zpass`, `renderva(..., doOQ)`) sigue activo. Si las líneas
  siguen, la causa está en esa estructura del pase. Si desaparecen, estaba en la decisión "todo oculto".
- Resultado: pendiente de la prueba en el visor.

### Resultado de la build 0251 (oqnoquery con todo visible, ruebli)

- **Las líneas siguen** aunque las consultas no decidan nada. Por tanto no vienen de la decisión de ocultar.
- Con todo visible vuelven los edificios lejanos y baja el rendimiento. Antes, con consultas reales, esos
  edificios desaparecían. Es decir: la PVS sola no oculta lo bastante.
- Con `oqfrags 0` (sin `doOQ`) las líneas desaparecían. Entre ese caso y este queda `doZP` (`zpass 1`):
  `doZP = doOQ && zpass`. Es la única diferencia que queda dentro del camino de oclusión.

### Build 0301: zpass 0 con doOQ activo

- Cambio por defecto: `VAR(zpass, 0, 0, 1)`. Sigue activo `doOQ` (no se dibujan consultas GL).
- Lectura: si las líneas desaparecen, el pase Z previo (`RENDERPASS_Z`) es la causa. Si siguen,
  la causa está en `renderva(..., doOQ)` o en el segundo bucle del pase Z (`oqrecover`).
- Resultado: pendiente de la prueba en el visor.

### Resultado de zpass 0 (build 0301, ruebli)

- **Con zpass 0 las líneas desaparecen.** La causa está en el pase Z previo (`doZP = doOQ && zpass`).
- Hipótesis (por lectura del código, sin probar): tras el bloque de consultas, `disablevattribs(cur, !doZP)`
  con `doZP` activo solo desactiva el atributo de vértice. Los de textura, normal y tangente quedan
  habilitados y con punteros de otro buffer (`bbvbo`). Build 0308: todos los atributos se desactivan
  tras el bloque de consultas, con `zpass` de nuevo en 1, para comprobar si las líneas desaparecen.
- Resultado: pendiente de la prueba en el visor.

### Resultado de la build 0308 (desactivar atributos tras consultas)

- **Las líneas volvieron** con `zpass 1`. La hipótesis de los atributos queda descartada.

### Build 0312: zprepass (pase de profundidad sin dibujar)

- Nuevo interruptor `zprepass` (por defecto 0 en esta build). Con 0 `renderzpass` no dibuja nada, así que el color
  se dibuja con la profundidad vacía.
- Lectura: si las líneas desaparecen, el problema está en la geometría del pase Z (`renderzpass`,
  VBO o shader `nocolorshader`). Si siguen, la causa está en el pase de color con `LEQUAL`
  (segundo bucle de `rendergeom`) o en la profundidad que deja otra parte del frame.
- Resultado: pendiente de la prueba en el visor.

### Resultado de la build 0313 (zprepass 0)

- **Las líneas desaparecen** con `zprepass 0`. Con `zprepass 1` vuelven. La causa está en lo que dibuja
  el pase de profundidad previo (`renderzpass`), no en el pase de color.
- Revisado en el código: `renderzpass` usa `changevbuf` con solo el puntero de posición, `nocolorshader` y
  `drawvatris` con `va->tris`. No se ve una diferencia obvia con el pase de color.
- Siguiente prueba propuesta: pintar el pase de profundidad en color, para ver en pantalla qué triángulos
  dibuja y si coinciden con las líneas.

### Build 0319: pase de profundidad en rojo (zpassdebug)

- `zpassdebug` (por defecto 1): `renderzpass` pinta con el shader `zdebug` (rojo) en vez de `nocolor`.
  Las zonas en rojo son las que solo dibuja el pase de profundidad y el color no tapa.
- Lectura: si las líneas aparecen en rojo, el pase Z dibuja triángulos que el color no. Si no hay rojo
  donde están las líneas, la profundidad que escribe el pase Z es la causa.
- Resultado: pendiente de la prueba en el visor.

### Resultado de la build 0319 (zpassdebug)

- **Las líneas se ven en rojo.** El pase de profundidad escribe píxeles que el color no conserva.
- Dos explicaciones posibles: (a) el color falla el test `LEQUAL` porque el prepass queda más cerca
  (transformaciones o precisión distintas); (b) el pase de color no dibuja esos triángulos (conjunto de
  triángulos distinto entre `renderzpass` y el pase de color).
- En el código, `nocolor` y los shaders de mundo usan la misma `camprojmatrix * vvertex`, así que (a) pesa menos.
  Siguiente comprobación propuesta: comparar, por VA, `va->tris` del prepass con los triángulos que dibuja
  el pase de color.

### Build 0325: prueba de desfase del pase de profundidad (zpassoffset)

- `zpassoffset` (por defecto 1) aplica `glPolygonOffset(1,1)` solo al pase de profundidad, con el pase
  rojo (`zpassdebug`) encendido.
- Lectura: si las líneas rojas desaparecen, el color se rechazaba por profundidad (caso a: prepass
  ligeramente más cerca). Si siguen en rojo, el pase de color no dibuja esos triángulos (caso b).
- Es solo diagnóstico: el desfase puede esconder fallos en contactos. No es la solución final.
- Resultado: pendiente de la prueba en el visor.

### Resultado de la build 0325 (zpassoffset)

- **La prueba no es concluyente.** La app crasheó (`sauvr crash sig=11`, 03:28 UTC, pc=0x755ef774f4,
  addr=0x7564903ff0). Desaparecieron algunas paredes, y a lo lejos se vio un edificio en rojo a través
  de un muro. Sin el desfase, las líneas rojas seguían en la build 0319.
- El crash no se puede simbolizar aún: el manejador solo registra `pc` y no la base de la librería, y no
  hay tombstones accesibles por adb.
- Siguiente paso propuesto: registrar la base de `libsauerquest.so` (`dladdr`) en el manejador de crash, o
  quitar el desfase y repetir la prueba roja para separar el crash del glitch.

### Build 0331: zpassoffset 0 (sin desfase), prueba roja

- Se quitó el desfase para separar el crash y las paredes desaparecidas de la prueba roja.
- `zpassdebug` sigue en 1 y `zprepass` en 1.
- Resultado: pendiente de la prueba en el visor (¿crash? ¿paredes? ¿líneas rojas?).

### Resultado de la build 0331 (sin desfase, prueba roja)

- **Las líneas salen en rojo otra vez.** El pase de profundidad escribe píxeles que el color no conserva.
- Se puede jugar. No se reporta crash en esta build. El crash de la 0325 pudo venir del desfase.
- Siguiente comprobación propuesta: comparar por VA los triángulos del pase de profundidad (`numtris`) con los
  que dibuja el pase de color, para ver si el conjunto de triángulos difiere.

### Comparación con upstream (Tesseract, lsalzman/tesseract)

- `renderzpass` de Tesseract es igual al nuestro (mismo `changevbuf` con solo posición, `nocolorshader`,
  mismos `numtris`). El pase de color también usa `GL_LEQUAL` con `multipassing`. Por tanto el diseño del
  prepass no es lo que difiere del upstream.
- Lo que sí es propio del port: `glInvalidateFramebuffer` del depth tras cada render (`rendertarget.h`,
  commit dfa1fa6), el camino GLES/Adreno y multiview. Siguiente prueba propuesta: desactivar el
  `glInvalidateFramebuffer` del depth y repetir la prueba roja.
- El repositorio sauerbraten/sauerbraten devolvió 404 en la ruta `src/engine/renderva.cpp` (rama master).

### Build 0341: sin glInvalidateFramebuffer del depth

- Se desactivó (`#if 0` en `rendertarget.h`) el invalidate del depth tras cada render, con `zpassdebug` y
  `zprepass` en 1 y `zpassoffset` en 0.
- Lectura: si las líneas rojas desaparecen, el invalidate es la causa (driver Adreno con profundidad
  descartada). Si siguen, no lo es.
- Resultado: pendiente de la prueba en el visor.

- Resultado de la build 0341: **las líneas siguen en rojo**, así que el invalidate del depth no es la causa.
- Observación del visor: las líneas **solo afectan la geometría del mapa**; los personajes y los objetos no
  se ven afectados. Eso apunta al camino de VAs (`renderzpass` sobre `va->tris`), no a los modelos.
- Siguiente comprobación propuesta: contar por frame los triángulos del pase de profundidad (suma de
  `numtris`) frente a los del pase de color, y revisar si el pase Z incluye caras de cielo (`va->sky`).

### Build 0347: conteo de triángulos del pase Z frente al color

- `renderzpass` acumula `vrztris` (triángulos del pase de profundidad, sin alpha) por frame. El
  telemetría sale una línea nueva: `sauvr zpass ztris=N vtris=M`, con el último frame.
- Lectura: si `ztris` > `vtris` de forma sostenida, el pase de profundidad dibuja triángulos que el
  color no dibuja (caso b). Si son iguales o casi, el conjunto es el mismo y el problema está en la
  profundidad o en el orden de dibujo.
- Pendiente: contar caras de cielo en el pase Z.
- Resultado: pendiente de la prueba en el visor (leer la telemetría después de jugar).

### Resultados de la build 0347 (ruebli, telemetría)

- `ztris=27689 vtris=44496` (último frame, estable en ~124 lecturas).
- La diferencia (~16.800) puede venir de superficies de mezcla y alfa, que cuentan en `vtris` pero no en el pase Z.

### Build 0403: contador de mezcla y alfa (mtris)

- `vrmtris` suma `blendtris + alphatris` de las VAs que entran al bucle principal. Telemetría:
  `sauvr zpass ztris=N vtris=M mtris=K`.
- Lectura: si `vtris - ztris` ≈ `mtris`, la diferencia es de superficies de mezcla y alfa, y el conjunto
  opaco coincide en cantidad. Si no, hay triángulos opacos que el color dibuja y el pase Z no.
- Resultado: pendiente de la prueba en el visor.

### Lectura de la build 0403 (ruebli, telemetría 04:04–04:09 UTC)

- Medias: `ztris=73402`, `vtris=173701`, `mtris=236`. La diferencia (~100.000) **no** la explican las superficies de mezcla y alfa (`mtris` ≈ 236).
- Error de medida: `vtris` se reinicia solo en el pase principal, pero se acumula en los pases de reflejo y refracción del mismo frame. Por eso `vtris` supera a `ztris` sin que haya un fallo real. La comparación 27.689 / 44.496 de la build 0347 tiene el mismo problema.
- Build 0410: `vrctris` se toma al final del pase principal (`if(mainpass) vrctris = vtris`) y la telemetría usa ese valor.
- Resultado: pendiente de la prueba en el visor.

### Lectura de la build 0410 (conteo corregido, ruebli, 04:10–04:19 UTC)

- Medias: `ztris=74905`, `vtris=73450`, `mtris=260`. Ahora los conteos coinciden: el pase de profundidad
  dibuja ~2% más triángulos que el color (~1.455 por frame, con variación entre frames).
- Conclusión: el pase de profundidad no dibuja mucha más geometría que el color. El conjunto de triángulos
  es casi el mismo; el excedente pequeño es el candidato más probable a las líneas rojas, pero no está confirmado.
- Siguiente paso propuesto: contar por VA los triángulos de más en el pase Z y pintar en rojo solo esas VAs.

### Hallazgo en el código y build 0426

- En el bucle de profundidad, un VA ocultado por PVS (`OCCLUDE_GEOM`) con `oqskip 0` **sí se dibuja en el pase Z**,
  pero el segundo bucle de color lo salta (`va->occluded >= OCCLUDE_GEOM`). El pase Z escribe profundidad que
  el color no dibuja. Eso explica el edificio rojo visto a través de un muro: su profundidad se escribió, pero
  nunca se pintó.
- Con `zprepass 0` no se dibuja ese pase, por eso las líneas desaparecían. Con `zpass 0` (sin pase Z) el color
  dibuja esos VAs en el primer bucle, y tampoco aparecían líneas.
- Build 0426: `if(doZP && va->occluded >= OCCLUDE_GEOM) continue;` antes de `renderva` en el bucle principal. Así el
  pase Z salta lo mismo que el color.
- Resultado: pendiente de la prueba en el visor (¿desaparecen las líneas rojas? ¿el edificio rojo?).

### Resultado de la build 0426 (ruebli)

- El usuario reporta zonas visibles solo en un ojo. Causa probable: `setviewcell(camera1->o)` (`rendergl.cpp`) se llama
  por ojo, y `camera1->o` incluye el desplazamiento de ojo. Cerca de un borde de celda PVS, un ojo puede
  caer en otra celda y marcar VAs como ocultos solo en ese ojo.
- Pendiente: confirmar si las líneas rojas desaparecieron con la 0426. Después: usar una sola celda PVS por frame
  (desde el cuerpo, no desde el ojo) o revertir el salto del pase Z.

### Telemetría con la build 0426 (ruebli, últimas 300 lecturas, ~04:37–04:46 UTC)

- `ztris=76037`, `vtris=76143`, `mtris=236`. La diferencia es ~105 triángulos por frame (0,1%).
- El excedente de ~1.455 triángulos desapareció con el salto del pase Z para VAs ocultos. **Pero las líneas rojas
  siguen**: el conjunto de triángulos ya coincide en número, así que la causa no es la cantidad de triángulos.
- Telemetría de mapa: fps ~54–60, draw ~1.600, glerr casi siempre 0 (algún 1 aislado), sin crash desde 03:28 UTC (build 0325).
- Siguiente paso propuesto: comparar profundidad, no geometría: `invariant gl_Position` en el shader `nocolor` y
  en los de mundo, y revisar si la misma posición produce la misma profundidad en ambos pases.

### Build 0454: invariant gl_Position en todos los vertex shaders

- Se añadió `invariant gl_Position;` a los vertex shaders generados (`src/engine/shader.cpp`, bloque `#define attribute in`).
  Así cada programa calcula gl_Position con la misma precisión y orden de operaciones.
- Lectura: si las líneas rojas desaparecen, la diferencia era de profundidad entre pases. Si siguen, la profundidad
  coincide y la causa está en otra parte (orden de dibujo o estado).
- Resultado: pendiente de la prueba en el visor.

- Resultado de la build 0454: **las líneas rojas siguen.** Con la precisión de gl_Position igualada, la
  profundidad no explica el glitch. Descartadas: cantidad de triángulos, precisión de gl_Position, y el
  invalidate del depth. Pendiente: orden de dibujo, estado de GL, y el problema de celda PVS por ojo.
- Siguiente prueba propuesta: en el pase de color usar `GL_EQUAL` con escrituras de profundidad desactivadas
  (el patrón clásico de prepass). Si las líneas desaparecen, sospechar del manejo de profundidad por tiles
  del Adreno (LRZ). Si la escena se rompe, el problema está en el orden o los estados.

### Build 0501: pase de color con GL_EQUAL tras el prepass (zpassequal)

- `zpassequal` (por defecto 1): en el segundo bucle de color con prepass, `glDepthFunc(GL_EQUAL)` en vez de `GL_LEQUAL`.
  Las superficies de mezcla y las cáusticas siguen con `GL_LEQUAL`.
- Lectura: si las líneas desaparecen, el manejo de profundidad por tiles (LRZ) del Adreno con LEQUAL es la causa
  probable. Si la escena se rompe (huecos generalizados), el orden de dibujo o un estado de GL es la causa.
- Resultado: pendiente de la prueba en el visor.

- Resultado de la build 0501: **la zona roja se densificó**, casi sólida, y solo en algunos ángulos se ve la retícula.
  Interpretación: con `GL_EQUAL` la mayoría de los píxeles del color fallan la prueba, así que la profundidad del
  prepass y la del color **no son iguales** en casi ningún píxel, no solo en los bordes. La diferencia es sistemática.
- Siguiente paso propuesto: volcar el vertex shader realmente compilado para `nocolor` y para un shader de mundo
  (el que usa el pase de color), y compararlos línea a línea (transformación, `camprojmatrix`, multiview, offsets).

### Volcado de shaders (build 0507, logcat SHADERDUMP)

- `nocolor` (vértice): `gl_Position = camprojmatrix[gl_ViewID_OVR] * vvertex;`, con `uniform mat4 camprojmatrix[2];`.
- `noglareworld` (mundo, pase de color): exactamente la misma expresión, con `void main(void)` y saltos de línea.
- Conclusión: el texto de los vertex shaders es idéntico en la transformación. La diferencia de profundidad no
  viene del código fuente de los shaders. Pendiente: comprobar que el uniform `camprojmatrix` tiene el mismo valor
  en ambos pases (un valor obsoleto o distinto por ojo explicaría la diferencia sistemática).

### Volcado CAMDUMP (build 0520, ruebli, 05:32 UTC)

- Pase Z y pase de color: `projdz=-1.0801425` en todas las lecturas, y las matrices de cada ojo son idénticas
  (`eye0d`, `eye1d`). La matriz de proyección y su corrección de profundidad no difieren entre pases.
- Conclusión: descartada la matriz. La diferencia sistemática de profundidad con `GL_EQUAL` está en el propio
  buffer de profundidad (formato o compresión) o en cómo lo maneja el driver Adreno, no en las matrices.
- Próximos pasos propuestos: (1) comprobar el formato del buffer de profundidad del FBO (16 o 24 bits) en el visor;
  (2) como alternativa jugable, `zpass 0` en Android, que ya quitó las líneas en pruebas anteriores, a costa del pase Z.

### Build 0604: prueba de rendimiento con oclusión real y sin pase Z

- Defaults: `zpass 0`, `oqnoquery 0`, `oqdraw 1`, `oqskip 1`. Las consultas de oclusión están activas y saltan
  los VAs ocultos; el pase de profundidad está apagado.
- Nota: hasta la 0558, `oqnoquery` estaba en 1, así que la oclusión no decidía nada. Por eso las mediciones de
  rendimiento de esas builds no sirven para comparar.
- Objetivo: medir fps y draw calls en ruebli con oclusión real y sin pase Z, y compararlo con la 0301 y las builds anteriores.
- Después: volver a la investigación del uniform camprojmatrix (chequeo CAMUNIF de la 0558).

### Crash con la build 0604 (ruebli, 00:09–00:10 hora local)

- No es una excepción de la app: el driver de GPU (`kgsl-3d0`) reportó fallos del contexto GL
  (`status 00800005`) en 00:09:31, 00:09:38 (x2) y 00:10:19 (x2), y luego `gpu fault threshold exceeded
  3 faults in 2000 msecs`. El driver mata el proceso, por eso no hay `sauvr crash` en la telemetría.
- Durante esos minutos `glerr=0` y `gllast=500`: las llamadas GL no dieron error. Eso apunta a comandos
  válidos para la API pero que hacen leer memoria fuera de rango en la GPU (por ejemplo, un dibujo de
  caja de consulta o un VBO/EBO con estado heredado).
- Cambiar la configuración en caliente (oqnoquery, oqskip, zpass) con consultas en vuelo puede dejar
  consultas sin empezar o estado a medias. Hay que probar sin cambiar nada.
- Hipótesis: el camino de consultas (`renderquery`/`startbb`) provoca los fallos de GPU. Es la misma familia
  de problemas por la que la oclusión se apagó en Android en su día.

### Resultado de la reproducción (build 0618, ruebli, sin cambiar ajustes)

- Con `oqnoquery 1` (ninguna consulta GL): **0 fallos de GPU** en ~6 minutos de partida, proceso vivo.
  fps ~72, draw ~344, lotes ~323.
- Con las consultas activas (build 0604, `oqnoquery 0`): fallos de GPU (`kgsl`, `status 00800005`) en menos de
  un minuto, y el driver mata el proceso. Reproducido dos veces.
- Conclusión: el camino de consultas de oclusión provoca los fallos de GPU en este driver. Con las consultas
  apagadas, el rendimiento es bueno y estable (los draw calls bajan porque la PVS sí recorta la escena).
- Pendiente: decidir si la oclusión por consultas se deja apagada en Android o se corrige su estado de GPU
  (`startbb`/`endbb` y los VBO/EBO de la caja).

## Decisión (2026-11-05)

- Android queda con PVS de 16, sin consultas (`oqnoquery 1`, `oqfrags 0`) y sin pase Z (`zpass 0`).
  `zpassdebug` y `zpassequal` vuelven a 0. Con eso iba a ~72 fps y ~344 draws, sin fallos de GPU.
- Las líneas del pase Z no se persiguen más: la profundidad del prepass no coincide con la del color en
  casi ningún píxel (prueba `GL_EQUAL`) con shaders y matrices iguales, lo que apunta al driver. En Adreno el
  LRZ ya hace el rechazo por profundidad, así que el prepass no aporta.
- Si hace falta más recorte, el camino es el culling por software (`swocclude.h`). Arreglos de esta ronda:
  - Prueba contra cada ojo (`geteyecamprojs`) y no contra la cámara central; un VA se descarta solo si queda
    oculto en las dos vistas.
  - Rasterizado conservador: el oclusor solo marca los píxeles que cubre enteros, con su profundidad más
    lejana dentro del píxel.
  - Los oclusores que cruzan el plano cercano se recortan en vez de descartarse.
  - Marca por frame en el `vtxarray` (`swframe`) en vez de buscar en una lista.
  - Telemetría `swus`: microsegundos de CPU del culling por software en el último frame.
- Pendiente: probar en el visor (sin geometría que desaparezca en ningún ojo) y comparar `swcull`, `draw`,
  `fps`, `p95` y `swus` con `swocclude 0` y 1.
