# Mapa scifi (ciudadela de metal y neón)

Generador: `tools/desktop/gen-scifi-map.mjs`. Salida en `android/app/src/main/assets/packages/base/`:
`scifi.ogz` (octree), `scifi.cfg` (texturas, cielo, niebla), `scifi.jpg` (miniatura del menú) y
`scifi.pvs` (potencialmente visible, horneado).

## Geometría

- Mundo de 2048 unidades (celdas de 8, rejilla de 256). Es el doble de hell.
- Plaza central de radio 36 con obelisco y franja de neón en el suelo.
- Anillo elevado de radio 60 a 68, con la superficie a 12 celdas del suelo y barandilla exterior.
- Cuatro escaleras en cruz (escalón de 1 celda cada 4) que suben de la plaza al anillo.
- Cuatro búnkeres de esquina de 40 celdas, con puerta hacia el centro y claraboya en el tejado.
- Muralla exterior de placas de 4 celdas de grosor.

## Regenerar y hornear

```bash
node tools/desktop/gen-scifi-map.mjs
```

Esto reescribe `scifi.ogz` y `scifi.cfg` sin hornear. Después hay que volver a hornear la luz
y el PVS; el PVS se invalida si el mapa cambia. Para solo la miniatura usa `--preview ruta.png`,
que no toca el mapa.

Luz (`calclight` en el escritorio, con `lightprecision 16` para más detalle que el valor por defecto de 32):

```bash
bin64/sauerbraten.exe "-qbin64/home-scifi" "-glog.txt" "-w1280" "-h720" "-t0" "-xmap scifi; lightprecision 16; calclight 1; savemap scifi; quit"
```

Ejecutar desde `android/app/src/main/assets`. El resultado queda en `bin64/home-scifi/packages/base/scifi.ogz`.
Copiarlo sobre `android/app/src/main/assets/packages/base/scifi.ogz`.

PVS: `npm run pvs:bake -- scifi` (después de copiar el mapa horneado).

## Miniatura

`scifi.jpg` se convierte desde el PNG del `--preview` con System.Drawing (JPEG, calidad 90).

## Registro

`MapList_DM = [duel7 ruebli hell scifi]` en `data/lists.cfg` y en la copia de los assets del visor.
