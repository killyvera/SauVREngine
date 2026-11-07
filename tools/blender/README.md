# Importar personajes GLB como modelos de jugador

Convierte un personaje GLB con rig de Mixamo (por ejemplo, los que exporta
Tripo) en un modelo de jugador del juego que hereda las animaciones y el
ragdoll de mrfixit. Así se hizo `packages/models/soldado`.

## Uso

```bash
npm run model:import -- "C:/ruta/modelo.glb" --name robot --title "Robot" --story "Texto del menú."
```

| Opción | Por defecto | Qué hace |
|---|---|---|
| `--name` | (obligatorio) | Carpeta e iconos: minúsculas, números y `_` |
| `--title` | el nombre | Nombre visible en el menú de modelos |
| `--story` | genérica | Texto del menú de modelos |
| `--mdlscale` | 916 | Tamaño visual (mrfixit 800; 916 es lo que se dejó al soldado). Solo afecta al dibujo, no a la caja de colisión |
| `--smooth` | 80 | Ángulo de suavizado de normales; 0 = facetado, 180 = todo suave |
| `--ref` | mrfixit | Modelo cuyo esqueleto, animaciones y ragdoll se heredan |

Necesita Blender (lo busca en `C:/Program Files/Blender Foundation`, o en la
variable `BLENDER`). Volver a ejecutarlo con el mismo `--name` reconvierte el
modelo sin registrarlo dos veces; sirve para ajustar escala o suavizado.

## Qué hace

1. **Conversión** (`glb2md5.py`, en Blender sin interfaz):
   - Importa el GLB y suelda los vértices duplicados (Tripo exporta cada
     triángulo con vértices propios, lo que se ve facetado).
   - Orienta el modelo (mirando a +x, izquierda en +y) y lo escala a la altura
     de mrfixit. **La malla no se deforma.**
   - Coloca los 75 joints de mrfixit, con sus orientaciones, en las
     articulaciones Mixamo del modelo; el modelo tiene esqueleto propio.
   - Pasa los pesos de cada hueso Mixamo a su joint de mrfixit (los meñiques
     van con el anular y las clavículas con el pecho).
   - Retargetea las 33 animaciones de mrfixit: mismas rotaciones, solo cambian
     las traslaciones. Las manos de mrfixit cuelgan de una cadena IK aparte
     (`ArmIK → HandGoal`) y se recolocan en cada frame al final del antebrazo,
     para que la mano y el arma sigan al brazo.
   - Ajusta el ragdoll (puntos y distancias) al cuerpo nuevo.
   - Escribe la textura a 1024 con variantes azul y roja, los `md5.cfg`
     (normal, `blue/`, `red/`) y los iconos de 64×64 del menú.
2. **Registro** (`import-model.mjs`): añade el modelo a `playermodels[]` y
   sube el máximo de `playermodel` en `src/fpsgame/render.cpp`. También añade
   su entrada a `game_fps.cfg` y el contador a `menus.cfg`, tanto en `data/`
   como en los assets de Android. Va sin la armadura ni el quad de mrfixit,
   que no encajan en otro cuerpo.

## Requisitos del GLB

- Rig de Mixamo con los nombres `mixamorig:*` (Hips, Spine, Spine1, Spine2,
  Neck, Head, brazos, piernas y dedos). Si faltan huesos, el conversor los
  manda a Hips y lo avisa.
- Pose en T o similar, con un solo material y una textura base. Las
  animaciones que traiga el GLB se ignoran.

## Comprobarlo

1. Compilar el escritorio: `npm run desktop:build`.
2. Abrir el juego con el modelo en tercera persona y el menú de modelos, que
   guarda capturas en `<home>/screenshot/`. Cambia `5` por el índice del
   modelo nuevo:

   ```bash
   cd android/app/src/main/assets && ../../../../../bin64/sauerbraten.exe -q<home> -glog.txt -w1280 -h800 -t0 "-xplayermodel 5; forceplayermodels 1; map duel7; sleep 4000 [thirdperson 1; thirdpersondistance 14]; sleep 6000 [screenshot tp.png]; sleep 6500 [showgui playermodel]; sleep 8500 [screenshot menu.png]; sleep 9000 [quit]"
   ```

3. En el Quest: `npm run apk:serve` (telemetría), `npm run apk:build` e
   instalar con `adb install -r dist/apk/SauVREngine-latest.apk`. Para verlo
   en todos los jugadores, deja temporalmente en el visor un `autoexec.cfg`
   con `playermodel N; forceplayermodels 1`:

   ```bash
   MSYS_NO_PATHCONV=1 adb shell "run-as org.sauvrengine.vr sh -c 'echo \"playermodel 5; forceplayermodels 1\" > files/autoexec.cfg'"
   ```

   Bórralo al terminar (`run-as org.sauvrengine.vr rm files/autoexec.cfg`).

## Hacer el commit

`android/app/src/main/assets/packages/` está en `.gitignore`, pero los modelos
se versionan igualmente, así que se añaden con `-f`:

```bash
git add -f android/app/src/main/assets/packages/models/<nombre> android/app/src/main/assets/packages/icons/<nombre>*.jpg
```

El modelo ocupa unos 6 MB, sobre todo por las animaciones propias.
