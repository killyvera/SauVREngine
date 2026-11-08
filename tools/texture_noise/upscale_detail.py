"""
Genera versiones más grandes de las texturas del pack, para que el mip que elige
la GPU al acercarse tenga más resolución que la original.

Para cada textura (desde su propia versión más grande disponible):
  1. escala a 2× (tope 2048) con Lanczos: la forma sale igual, sin inventar estructura;
  2. aerosol: en los bordes, algunos píxeles se dispersan a una posición cercana y
     quedan semitransparentes, para que el escalón de píxel se vea como un
     desenfoque suave y no como bloques;
  3. grano fino, tintado por el color local, con poca intensidad.

El detalle añadido no es información real: suaviza el paso de resolución, no
reconstruye rasgos que la original no tiene. Los mapas de datos (_n, _bump,
_spec...) se omiten, igual que en add_noise.py, y las texturas con alfa conservan
su transparencia original.

Uso:
    py -3 upscale_detail.py <archivo_o_carpeta> --out DIR [--max 2048] [--scale 2]
                            [--spray 0.35] [--spray-radius 1.2] [--amount 0.02] [--seed 1]
"""

import argparse
import os
import re
import sys

import numpy as np
from PIL import Image, ImageFilter

EXTENSIONES = {'.png', '.jpg', '.jpeg', '.tga', '.bmp'}
EXCLUIR_DEFECTO = r'_(n|nm|normal|normals|bump|height|h|hm|spec|s|sm|sc|cc|old|gloss|mask|a|alpha|k|glow|d|decal)$'


def octava(ruido, radio):
    """Ruido ya normalizado, suavizado con un radio dado (px de la imagen destino)."""
    im = Image.fromarray(((ruido * 40) + 128).clip(0, 255).astype(np.uint8))
    arr = np.asarray(im.filter(ImageFilter.GaussianBlur(radius=radio)), dtype=np.float32)
    return (arr - 128.0) / 40.0


def grano(alto, ancho, rng, radio):
    """Grano a la escala de los rasgos de la fuente (sin octavas de un píxel: parecía arena)."""
    return octava(rng.normal(0.0, 1.0, size=(alto, ancho)).astype(np.float32), radio)


def aerosol(rgb, alfa, spray, radio, rng):
    """Dispersa píxeles de los bordes a una posición cercana con transparencia.

    Solo actúa donde hay borde (la pendiente del brillo), así que las zonas planas
    quedan intactas. Las textures tilean, por eso el desplazamiento da la vuelta.
    """
    alto, ancho = rgb.shape[:2]
    lum = rgb.mean(axis=-1)
    gy, gx = np.gradient(lum)
    borde = np.hypot(gx, gy)
    ref = np.percentile(borde, 90) + 1e-6
    prob = spray * np.clip(borde / ref, 0.0, 1.0)

    lim = max(1, int(np.ceil(radio * 2.5)))
    dy = np.clip(np.round(rng.normal(0.0, radio, (alto, ancho))), -lim, lim).astype(int)
    dx = np.clip(np.round(rng.normal(0.0, radio, (alto, ancho))), -lim, lim).astype(int)
    yy, xx = np.indices((alto, ancho))
    sy = (yy + dy) % alto
    sx = (xx + dx) % ancho

    usa = rng.random((alto, ancho)) < prob
    # la transparencia crece con la distancia de la muestra: el píxel disperso se diluye
    t = np.where(usa, rng.uniform(0.35, 0.8, (alto, ancho)), 0.0)[..., None]
    rgb_out = rgb * (1.0 - t) + rgb[sy, sx] * t
    alfa_out = alfa * (1.0 - t) + alfa[sy, sx] * t
    return rgb_out, alfa_out


def genera(ruta, salida_dir, args, rng):
    img = Image.open(ruta)
    tiene_alfa = img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info)
    img = img.convert('RGBA')
    ancho0, alto0 = img.size
    lado = min(args.max, round(max(ancho0, alto0) * args.scale))
    if lado <= max(ancho0, alto0):
        return None
    ancho = lado if ancho0 >= alto0 else round(ancho0 * lado / alto0)
    alto = lado if alto0 >= ancho0 else round(alto0 * lado / ancho0)

    escalada = np.asarray(img.resize((ancho, alto), Image.LANCZOS), dtype=np.float32)
    rgb = escalada[..., :3]
    alfa = escalada[..., 3:4]

    rgb, alfa = aerosol(rgb, alfa, args.spray, args.spray_radius, rng)

    if args.blend > 0:
        # mezcla suave con una versión desenfocada: quita el escalón de píxel sin perder la forma
        desenfocada = np.asarray(
            Image.fromarray(rgb.clip(0, 255).astype(np.uint8)).filter(
                ImageFilter.GaussianBlur(radius=args.blend_radius * ancho / ancho0)),
            dtype=np.float32)
        rgb = (1.0 - args.blend) * rgb + args.blend * desenfocada

    lum = rgb.mean(axis=-1, keepdims=True) / 255.0
    radio = max(0.8, 1.5 * ancho / ancho0)
    n = grano(alto, ancho, rng, radio)[..., None]
    rgb = np.clip(rgb + args.amount * 255.0 * n * (0.35 + lum), 0, 255)

    res = np.concatenate([rgb, alfa], axis=-1).astype(np.uint8)
    salida = Image.fromarray(res, 'RGBA')
    if not tiene_alfa:
        salida = salida.convert('RGB')
    os.makedirs(salida_dir, exist_ok=True)
    # misma extensión que la original (jpg con calidad alta), así no chocan png y jpg del mismo nombre
    nombre, ext = os.path.splitext(os.path.basename(ruta))
    ext = ext.lower()
    if ext in ('.jpg', '.jpeg'):
        destino = os.path.join(salida_dir, nombre + ext)
        salida.save(destino, quality=95)
    else:
        destino = os.path.join(salida_dir, nombre + '.png')
        salida.save(destino)
    return destino


def recoge(entrada, excluir):
    if os.path.isfile(entrada):
        candidatos = [entrada]
    else:
        candidatos = [os.path.join(r, n) for r, _, ns in os.walk(entrada) for n in ns]
    archivos = []
    for ruta in sorted(candidatos):
        nombre, ext = os.path.splitext(os.path.basename(ruta))
        if ext.lower() not in EXTENSIONES:
            continue
        if excluir and re.search(excluir, nombre, re.IGNORECASE):
            continue
        archivos.append(ruta)
    return archivos


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('entrada', help='textura o carpeta (recursiva)')
    ap.add_argument('--out', required=True, help='carpeta de salida (conserva la estructura relativa)')
    ap.add_argument('--scale', type=float, default=2.0, help='factor de escala (defecto 2)')
    ap.add_argument('--max', type=int, default=2048, help='lado máximo de salida (defecto 2048)')
    ap.add_argument('--spray', type=float, default=0.35, help='probabilidad de dispersión en bordes, 0..1')
    ap.add_argument('--spray-radius', type=float, default=1.2, help='radio del aerosol en píxeles de salida')
    ap.add_argument('--amount', type=float, default=0.02, help='intensidad del grano, 0..0.3')
    ap.add_argument('--blend', type=float, default=0.0, help='mezcla con versión desenfocada, 0..1 (defecto 0 = apagada)')
    ap.add_argument('--blend-radius', type=float, default=1.0, help='radio del desenfoque en texels de la fuente')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--exclude', default=EXCLUIR_DEFECTO)
    args = ap.parse_args()

    if not 0.0 <= args.spray <= 1.0 or not 0.0 <= args.amount <= 0.3:
        sys.exit('--spray debe estar entre 0 y 1, y --amount entre 0 y 0.3')

    archivos = recoge(args.entrada, args.exclude)
    if not archivos:
        sys.exit('no hay texturas en ' + args.entrada)

    base = args.entrada if os.path.isdir(args.entrada) else os.path.dirname(args.entrada)
    rng = np.random.default_rng(args.seed)
    hechas = 0
    for ruta in archivos:
        rel = os.path.dirname(os.path.relpath(ruta, base))
        destino_dir = os.path.join(args.out, rel)
        try:
            destino = genera(ruta, destino_dir, args, rng)
        except Exception as e:
            print('error', ruta, e, file=sys.stderr)
            continue
        if destino:
            hechas += 1
            print('ok', destino)
        else:
            print('sin cambio (ya es igual o mayor)', ruta)
    print(f'{hechas}/{len(archivos)} texturas generadas')


if __name__ == '__main__':
    main()
