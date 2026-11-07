#!/usr/bin/env node
// Importa un personaje GLB con rig de Mixamo como modelo de jugador: lo
// convierte con Blender (glb2md5.py) y lo registra en el juego (render.cpp,
// game_fps.cfg y menus.cfg, en data/ y en los assets de Android).
//   npm run model:import -- <modelo.glb> --name soldado --title "Soldado" [--story "..."]
//                           [--mdlscale 916] [--smooth 80] [--ref mrfixit]
// Volver a ejecutarlo con el mismo --name reconvierte el modelo y no lo
// registra dos veces. Ver tools/blender/README.md.
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const assets = path.join(repo, 'android', 'app', 'src', 'main', 'assets');
const models = path.join(assets, 'packages', 'models');

const args = process.argv.slice(2);
const opt = (n, d) => { const i = args.indexOf(n); return i >= 0 && args[i + 1] ? args[i + 1] : d; };
const glb = args.find((a, i) => !a.startsWith('--') && !(i > 0 && args[i - 1].startsWith('--')));
const name = opt('--name');
if (!glb || !name || !/^[a-z0-9_]+$/.test(name)) {
  console.error('uso: npm run model:import -- <modelo.glb> --name nombre_en_minusculas --title "Nombre visible" [--story "..."] [--mdlscale 916] [--smooth 80] [--ref mrfixit]');
  process.exit(1);
}
const title = opt('--title', name);
const story = opt('--story', `${title}. Lleva el esqueleto y los movimientos de Mr. Fixit.`);
const ref = opt('--ref', 'mrfixit');
if (!fs.existsSync(glb)) { console.error(`no existe ${glb}`); process.exit(1); }

function findBlender() {
  if (process.env.BLENDER) return process.env.BLENDER;
  const base = 'C:/Program Files/Blender Foundation';
  const dirs = fs.existsSync(base) ? fs.readdirSync(base).filter((d) => d.startsWith('Blender')).sort().reverse() : [];
  for (const d of dirs) { const exe = path.join(base, d, 'blender.exe'); if (fs.existsSync(exe)) return exe; }
  console.error('No encuentro blender.exe; instala Blender o pon su ruta en BLENDER.'); process.exit(1);
}

// 1. Conversión con Blender.
const r = spawnSync(findBlender(), [
  '-b', '--factory-startup', '--python-exit-code', '1', '-P', path.join(repo, 'tools', 'blender', 'glb2md5.py'), '--',
  '--glb', path.resolve(glb), '--ref', path.join(models, ref, `${ref}.md5mesh`), '--out', path.join(models, name),
  '--name', name, '--icons', path.join(assets, 'packages', 'icons'),
  '--mdlscale', opt('--mdlscale', '916'), '--smooth', opt('--smooth', '80'),
], { encoding: 'utf8', maxBuffer: 1 << 26 });
const out = (r.stdout ?? '') + (r.stderr ?? '');
for (const l of out.split('\n')) if (/glb2md5|Error|Traceback|^\s+File /.test(l)) console.log(l.trimEnd());
if (r.status !== 0) { console.error('Blender falló'); process.exit(1); }

// 2. Registro en el juego (idempotente).
function edit(file, fn) {
  const text = fs.readFileSync(file, 'utf8');
  const eol = text.includes('\r\n') ? '\r\n' : '\n';
  const next = fn(text.split(/\r?\n/), eol);
  if (next) { fs.writeFileSync(file, next.join(eol)); console.log(`registrado en ${path.relative(repo, file)}`); }
}

edit(path.join(repo, 'src', 'fpsgame', 'render.cpp'), (lines) => {
  if (lines.some((l) => l.includes(`{ "${name}", "${name}/blue"`))) return null;
  const start = lines.findIndex((l) => /static const playermodelinfo playermodels\[\d+\] =/.test(l));
  const end = lines.findIndex((l, i) => i > start && /^\s*};/.test(l));
  const n = Number(lines[start].match(/\[(\d+)\]/)[1]);
  lines[start] = lines[start].replace(/\[\d+\]/, `[${n + 1}]`);
  let last = end - 1;
  while (/^\s*\/\//.test(lines[last])) last--;
  if (!/,\s*$/.test(lines[last])) lines[last] = lines[last].replace(/\s*$/, ',');
  lines.splice(end, 0, `        { "${name}", "${name}/blue", "${name}/red", "mrfixit/hudguns", NULL, NULL, { NULL, NULL, NULL }, "${name}", "${name}_blue", "${name}_red", true }`);
  const v = lines.findIndex((l) => l.includes('VARFP(playermodel, 0, 0,'));
  lines[v] = lines[v].replace(/VARFP\(playermodel, 0, 0, \d+,/, `VARFP(playermodel, 0, 0, ${n},`);
  return lines;
});

for (const data of [path.join(repo, 'data'), path.join(assets, 'data')]) {
  edit(path.join(data, 'game_fps.cfg'), (lines) => {
    if (lines.some((l) => new RegExp(`^playermodeldir\\d+\\s*= "${name}"`).test(l))) return null;
    const stories = lines.map((l, i) => [l.match(/^playermodelstory(\d+)\s*=/), i]).filter(([m]) => m);
    const [[m, at]] = stories.slice(-1);
    const k = Number(m[1]) + 1;
    lines.splice(at + 1, 0, '', `playermodeldir${k}   = "${name}"`, `playermodelicon${k}  = "${name}"`,
      `playermodelname${k}  = "${title}"`, `playermodelstory${k} = "${story.replace(/"/g, "'")}"`);
    return lines;
  });
  edit(path.join(data, 'menus.cfg'), (lines) => {
    const cfg = fs.readFileSync(path.join(data, 'game_fps.cfg'), 'utf8');
    const count = (cfg.match(/^playermodeldir\d+\s*=/gm) ?? []).length;
    const i = lines.findIndex((l) => /defvar playermodelcount 1 \d+ 0/.test(l));
    if (lines[i].includes(`1 ${count} 0`)) return null;
    lines[i] = lines[i].replace(/defvar playermodelcount 1 \d+ 0/, `defvar playermodelcount 1 ${count} 0`);
    return lines;
  });
}

console.log(`\nListo: packages/models/${name}. Siguiente: npm run desktop:build y probarlo (tools/blender/README.md).`);
