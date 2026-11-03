# Atlas de texturas para reducir draw calls (ruebli)

## Problema medido

- `ruebli.ogz`: 412 105 hojas del octree, 109 slots de textura distintos en las caras
  (herramienta: lector de `.ogz` del backup, conteo por slot de `tex[0..5]`).
- Reparto de caras: el slot 1 tiene el 23 %, el 991 el 18 %, el 649 el 9 %. Los 25 primeros
  cubren el 94 % de las caras.
- Cada cambio de textura entre superficies corta un lote de render (`mergetexs` /
  `renderbatches` en `renderva.cpp`). Con 109 texturas en juego, el número de lotes de
  mundo crece con la cantidad de texturas visibles por frame.
- Medición en partida (ruebli, preset rendimiento, build `43b4f41`): 2000–2400 lotes y
  2350 draw calls en vistas densas, frente a unos 1000 en vistas normales.

## Memoria: no es el problema

Las texturas que más se usan son pequeñas. Medidas en el APK original
(`dist/apk/sauerbraten-vr.apk`, extraídas a scratchpad):

| Textura | Tamaño |
|---|---|
| textures/fatum/light.jpg | 64×64 |
| textures/fatum/redbricks.jpg | 64×64 |
| textures/fatum/ga.jpg | 64×64 |
| textures/fatum/oak1.jpg | 256×64 |
| textures/fatum/grey.jpg | 256×256 |
| textures/fatum/metal2.jpg | 256×256 |
| blikjebier/akaritori/floor7.jpg | 256×128 |
| philipk/pk01_gra_floor02_d.jpg | 128×128 |
| ik2k/ik_wpaperplain128c.jpg | 128×128 |
| textures/fatum/ornament2.jpg | 128×192 |
| textures/nieb/clone/plaster01.jpg | 512×512 |
| textures/nieb/clone/brick09.jpg | 512×512 |
| textures/nieb/clone/concrete07.jpg | 512×512 |
| textures/nieb/clone/metal_plate01-tan.jpg | 512×512 |
| textures/nieb/clone/woodchip02.jpg | 512×512 |

Suma de estas 15 en RGBA8 sin mipmaps: **6.0 MB**. Con mipmaps, unos 8 MB. Un atlas no
ahorra memoria de forma apreciable; su beneficio es solo de lotes.

Las texturas que faltan en `android/app/src/main/assets/packages/` están en el APK original,
no en el repositorio. Cualquier medición de memoria tiene que leerlas de ahí.

## Qué existe ya (búsqueda)

- No encontramos una solución open source que haga este atlas para Cube 2 / Sauerbraten.
- Tesseract (fork de Cube 2, lsalzman/tesseract) usa atlas solo para sombras, y quitó los
  lightmaps. No sirve para texturas difusas de mundo.
- Técnica general conocida: atlas con envoltura de UV dentro de cada subrectángulo y
  derivadas explícitas (`textureGrad`) para evitar costuras en mipmaps. Requiere cambiar los
  shaders del mundo y tiene costuras si no hay margen.

## Reinterpretación recomendada: texture arrays

Usar `GL_TEXTURE_2D_ARRAY` (disponible en GLES 3.0+, el visor usa GLES 3.2):

- Una capa por textura. `GL_REPEAT` funciona por capa: no hay costuras ni envoltura de UV.
- Los mipmaps se generan por capa: no hay problema de derivadas.
- Cada cara guarda su capa en la coordenada de textura (`texcoord0` pasa a `vec3`: u, v,
  capa). El lote deja de depender de la textura: todas las caras de un array van en un lote.
- Restricción: todas las capas de un array tienen el mismo tamaño. Solución: dos arrays,
  uno de 256×256 para las texturas de 64 a 256 y otro de 512×512 para las de 512 (las
  pequeñas se pueden escalar a 256 sin pérdida visible porque se repiten).
- Memoria: 256² RGBA8 = 256 KB por capa; 512² = 1 MB por capa. Con 109 capas en el peor caso,
  unos 60–110 MB sin comprimir. Comprimido en ASTC 8×8 baja a una décima parte. Hay que medir
  el límite `GL_MAX_ARRAY_TEXTURE_LAYERS` en el visor (suele ser ≥ 256).

### Cambios en el motor (no hechos todavía)

1. Herramienta de horneado: empaqueta los slots de cada mapa en uno o dos arrays y reescribe
   el `.cfg` (o un índice de capas) sin tocar el `.ogz`.
2. Vértices del mundo: añadir la capa como tercera componente de `texcoord0`
   (`renderva.cpp`, formato de vértice de VA).
3. Shaders del mundo (`glsl.cfg`): `sampler2D` → `sampler2DArray` y `texture2D(tex0, uv)` →
   `texture(tex0, vec3(uv, layer))` en las variantes de mundo. Las variantes de sombra,
   agua y dynlight heredan el cambio.
4. Batching: agrupar VAs por array en vez de por textura (`mergetexs`).

## Pendiente antes de implementar

- Resolver los índices de variante de vslot (1709, 1714, 1711, 1735, 1715, 1713, 1722…). Son
  vslots con cambios de rotación o escala, no slots base. Hay que seguir la cadena `prev`
  hasta el slot base para saber qué textura es.
- Prototipo medible: un mapa con un array y lotes antes/después con telemetría (`draw`,
  `lotes`, `tick`, `gpu`).

## Decisión

No se implementa todavía. Primero el prototipo de medición: si los lotes de mundo caen a la
mitad o menos en ruebli, el cambio en el motor se justifica. Si caen poco, el problema está en
los modelos (bots y objetos), y el atlas no es la solución.

## Medición de lotes (build fbb15cb, ruebli, solo, rendimiento)

Promedios por frame, 182 segundos en ruebli, sin sombra real (`sm 0`), con blobs:

| Campo | Valor | Qué mide |
|---|---|---|
| `lotes` | 861 | lotes de mundo (cambios de shader por batch) |
| `shdiff` | 91 (11 %) | cambio de shader distinto: tipo bump o estándar, ligado a la textura |
| `shvar` | 762 (89 %) | variante del mismo shader: luz dinámica o sombra |
| `slotsw` | 551 | cambios de textura; sin cambio de shader no generan lote nuevo |

Conclusión: los cortes de lote vienen sobre todo de **variantes de luz dinámica**, no de la
textura. Un atlas o array de texturas atacaría como mucho el 11 %. Antes de hacer atlas hay que
probar `maxdynlights 0` (y luego agrupar las superficies por máscara de luz).
