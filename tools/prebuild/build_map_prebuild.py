"""
Prebuild por mapa: lista las texturas que declara el .cfg del mapa, genera la
versión escalada (2x, tope 1024, sin aerosol ni mezcla) de las que tienen
original de color, y deja un manifiesto con cada slot.

Uso:
    py -3 build_map_prebuild.py <mapa> --originales DIR [--salida DIR]

  --originales  carpeta con el pack completo (packages/), p. ej. el del dispositivo
  --salida      por defecto prebuild/maps/<mapa> dentro del repo

Los mapas de datos (_n, _nm, _hm, _sm, _sc, _cc, _old, _normal, _spec...) no se tocan
y se copian tal cual si existen. Las texturas sin original quedan marcadas como
"missing" en el manifiesto.
"""

import argparse
import json
import os
import re
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'texture_noise'))
import upscale_detail as ud  # noqa: E402

DATOS = re.compile(r'_(n|nm|normal|normals|bump|height|h|hm|spec|s|sm|sc|cc|old|gloss|mask|a|alpha|k|glow|d|decal)$', re.I)
CFG_TEX = re.compile(r'^\s*texture\s+0\s+"([^"]+)"', re.M)


class Args:
    scale = 2.0
    max = 1024
    spray = 0.0
    spray_radius = 1.2
    amount = 0.0
    blend = 0.0
    blend_radius = 1.5


def slots_del_cfg(ruta_cfg):
    """Rutas de los slots de difusa, en el orden en que el motor los numera."""
    with open(ruta_cfg, encoding='utf-8', errors='replace') as f:
        texto = f.read()
    return CFG_TEX.findall(texto)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mapa')
    ap.add_argument('--originales', required=True)
    ap.add_argument('--salida')
    args = ap.parse_args()

    cfg = os.path.join(REPO, 'android', 'app', 'src', 'main', 'assets', 'packages', 'base', args.mapa + '.cfg')
    if not os.path.isfile(cfg):
        sys.exit('no existe el cfg del mapa: ' + cfg)
    salida = args.salida or os.path.join(REPO, 'prebuild', 'maps', args.mapa)
    tex_dir = os.path.join(salida, 'textures')
    os.makedirs(tex_dir, exist_ok=True)

    rutas = slots_del_cfg(cfg)
    manifiesto = {'mapa': args.mapa, 'fuente_cfg': os.path.relpath(cfg, REPO).replace(os.sep, '/'),
                  'slots': []}
    cuenta = {'escalada': 0, 'original': 0, 'dato': 0, 'missing': 0}
    rng = None

    for indice, rel in enumerate(rutas):
        origen = os.path.join(args.originales, rel)
        entrada = {'indice': indice, 'ruta': rel}
        nombre = os.path.splitext(os.path.basename(rel))[0]
        if not os.path.isfile(origen):
            entrada['estado'] = 'missing'
            cuenta['missing'] += 1
            manifiesto['slots'].append(entrada)
            continue
        if DATOS.search(nombre):
            destino = os.path.join(tex_dir, rel)
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            with open(origen, 'rb') as fi, open(destino, 'wb') as fo:
                fo.write(fi.read())
            entrada['estado'] = 'dato'
            cuenta['dato'] += 1
            manifiesto['slots'].append(entrada)
            continue
        dest_dir = os.path.join(tex_dir, os.path.dirname(rel))
        import numpy as np
        if rng is None:
            rng = np.random.default_rng(1)
        resultado = ud.genera(origen, dest_dir, Args, rng)
        if resultado:
            entrada['estado'] = 'escalada'
            entrada['archivo'] = os.path.relpath(resultado, salida).replace(os.sep, '/')
            cuenta['escalada'] += 1
        else:
            destino = os.path.join(tex_dir, rel)
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            with open(origen, 'rb') as fi, open(destino, 'wb') as fo:
                fo.write(fi.read())
            entrada['estado'] = 'original'
            entrada['archivo'] = rel
            cuenta['original'] += 1
        manifiesto['slots'].append(entrada)

    manifiesto['resumen'] = cuenta
    with open(os.path.join(salida, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifiesto, f, ensure_ascii=False, indent=2)
    print(args.mapa, cuenta, '->', salida)


if __name__ == '__main__':
    main()
