"""
Dispersa la definición de las texturas mezclándolas con grano en su propio color.

Para cada imagen se calcula el color medio de los píxeles opacos y se mezcla
cada píxel con un "ruido" alrededor de ese color:

    out = (1 - strength) * original + strength * (media + N(0, grain))

Así el grano sale en la paleta de la propia textura (no mete colores ajenos)
y los detalles finos pierden nitidez. El canal alfa no se toca.

Uso:
    py -3 add_noise.py <carpeta_o_imagen> [--out DIR] [--strength 0.25]
                       [--grain 24] [--seed 1] [--dry-run]

Sin --out, las imágenes se sobrescriben: haz copia de seguridad o usa --out.
"""

import argparse
import os
import re
import sys

import numpy as np
from PIL import Image

EXTENSIONES = {'.png', '.jpg', '.jpeg', '.tga', '.bmp'}
# Mapas de datos (normales, bump, especular...): el ruido les rompe el significado.
EXCLUIR_DEFECTO = r'_(n|normal|normals|bump|height|spec|gloss|mask)$'


def procesa(ruta_in, ruta_out, strength, grain, rng):
    img = Image.open(ruta_in)
    modo = img.mode
    tiene_alfa = modo in ('RGBA', 'LA') or (modo == 'P' and 'transparency' in img.info)
    rgba = np.asarray(img.convert('RGBA'), dtype=np.float32)
    rgb = rgba[..., :3]
    alfa = rgba[..., 3:4]

    opacos = alfa[..., 0] > 0
    if not opacos.any():
        return False
    media = rgb[opacos].mean(axis=0)

    ruido = rng.normal(0.0, grain, size=rgb.shape).astype(np.float32)
    capa = media + ruido
    out_rgb = (1.0 - strength) * rgb + strength * capa
    out_rgb = np.clip(out_rgb, 0, 255)

    resultado = np.concatenate([out_rgb, alfa], axis=-1).astype(np.uint8)
    salida = Image.fromarray(resultado, 'RGBA')
    if modo in ('RGB', 'L', 'P') and not tiene_alfa:
        salida = salida.convert('RGB')
    os.makedirs(os.path.dirname(ruta_out) or '.', exist_ok=True)
    salida.save(ruta_out)
    return True


def recoge(entrada, excluir):
    if os.path.isfile(entrada):
        candidatos = [entrada]
    else:
        candidatos = []
        for raiz, _, nombres in os.walk(entrada):
            for nombre in nombres:
                candidatos.append(os.path.join(raiz, nombre))
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
    ap.add_argument('entrada', help='imagen o carpeta (se recorre recursivamente)')
    ap.add_argument('--out', help='carpeta de salida (conserva la estructura relativa)')
    ap.add_argument('--strength', type=float, default=0.25, help='mezcla con el grano, 0..1 (defecto 0.25)')
    ap.add_argument('--grain', type=float, default=24.0, help='desviación del ruido en niveles 0..255 (defecto 24)')
    ap.add_argument('--seed', type=int, default=1, help='semilla para reproducibilidad')
    ap.add_argument('--exclude', default=EXCLUIR_DEFECTO,
                    help='regex sobre el nombre sin extensión que se omite (defecto: normales/bump/especular/máscaras)')
    ap.add_argument('--dry-run', action='store_true', help='solo lista lo que procesaría')
    args = ap.parse_args()

    if not 0.0 <= args.strength <= 1.0:
        sys.exit('--strength debe estar entre 0 y 1')

    archivos = recoge(args.entrada, args.exclude)
    if not archivos:
        sys.exit('no se encontraron imágenes en ' + args.entrada)

    base = args.entrada if os.path.isdir(args.entrada) else os.path.dirname(args.entrada)
    rng = np.random.default_rng(args.seed)
    hechos = 0
    for ruta in archivos:
        if args.out:
            rel = os.path.relpath(ruta, base)
            destino = os.path.join(args.out, rel)
        else:
            destino = ruta
        if args.dry_run:
            print('->', ruta, '=>', destino)
            continue
        try:
            if procesa(ruta, destino, args.strength, args.grain, rng):
                hechos += 1
                print('ok', destino)
            else:
                print('omitida (sin píxeles visibles)', ruta)
        except Exception as e:
            print('error', ruta, e, file=sys.stderr)

    if not args.dry_run:
        print(f'{hechos}/{len(archivos)} imágenes procesadas')


if __name__ == '__main__':
    main()
