#!/usr/bin/env node
// Genera el mapa "scifi" (ciudadela de metal y neón) para SauVREngine.
//   node tools/desktop/gen-scifi-map.mjs [--seed n]
// Escribe packages/base/scifi.ogz y scifi.cfg. Mundo de 2048 unidades (el doble que hell):
// celdas de 8 unidades en una rejilla de 256 por lado, plegada en octree (MAPVERSION 33).
// Plaza central con obelisco, anillo elevado de 12 celdas con escaleras en cruz, y cuatro
// búnkeres de esquina con tejado de claraboya. La luz no sale de aquí: se hornea en el
// desktop con `calclight 1` y `savemap scifi` (ver docs/mapa-scifi.md).
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const outDir = path.join(repo, 'android', 'app', 'src', 'main', 'assets', 'packages', 'base');
const args = process.argv.slice(2);
const opt = (name) => (args.indexOf(name) >= 0 ? args[args.indexOf(name) + 1] : null);
const seed = Number(opt('--seed') ?? 2048);

// ---- formato (src/engine/world.h, worldio.cpp, octa.h, shared/iengine.h, shared/ents.h)
const MAPVERSION = 33;
const WORLD = 2048;                       // worldsize, potencia de 2
const CELL = 8;                           // lado del cubo más pequeño, en unidades
const G = WORLD / CELL;                   // celdas por lado de la rejilla (256)
const OCTSAV_CHILDREN = 0, OCTSAV_EMPTY = 1, OCTSAV_SOLID = 2;
const ET = { LIGHT: 1, PLAYERSTART: 3, SHELLS: 8, BULLETS: 9, ROCKETS: 10, RIFLEROUNDS: 11,
    GRENADES: 12, CARTRIDGES: 13, HEALTH: 14, HEALTHBOOST: 15, GREENARMOUR: 16, YELLOWARMOUR: 17, QUADDAMAGE: 18 };

// ---- materiales: código de vóxel -> slot de textura (orden de los slots en scifi.cfg)
const V = { AIR: 0, BASE: 1, FLOOR: 2, PLATE: 3, PANEL: 4, GLOW: 5, METAL: 6 };
const SLOT = [0, 2, 3, 4, 5, 6, 7];      // AIR, BASE, FLOOR, PLATE, PANEL, GLOW, METAL

// ---- geometría en celdas (x, y, z). FLOOR_Z es la celda sólida superior del suelo; aire desde 6.
const C = G / 2;                          // centro (128)
const FLOOR_Z = 5;
const PLAZA_R = 36;                       // radio de la plaza al suelo
const RING_R0 = 60, RING_R1 = 68;         // anillo elevado
const RING_TOP = 11;                      // celda sólida superior del anillo (superficie a 12 celdas)
const BUNKER = 40;                        // lado de cada búnker
const BUNKERS = [[20, 20, 'E'], [196, 20, 'W'], [20, 196, 'E'], [196, 196, 'W']];

const rnd = mulberry32(seed);
const ri = (a, b) => a + Math.floor(rnd() * (b - a + 1));
function mulberry32(a) {
    return () => {
        a = (a + 0x6D2B79F5) | 0;
        let t = Math.imul(a ^ (a >>> 15), 1 | a);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

// ---- rejilla de vóxeles
const grid = new Uint8Array(G * G * G);
const at = (x, y, z) => (z * G + y) * G + x;
const inside = (x, y, z) => x >= 0 && y >= 0 && z >= 0 && x < G && y < G && z < G;
const get = (x, y, z) => (inside(x, y, z) ? grid[at(x, y, z)] : V.PLATE);

function box(x0, x1, y0, y1, z0, z1, v) {
    for (let z = Math.max(z0, 0); z <= Math.min(z1, G - 1); z++)
        for (let y = Math.max(y0, 0); y <= Math.min(y1, G - 1); y++)
            for (let x = Math.max(x0, 0); x <= Math.min(x1, G - 1); x++) grid[at(x, y, z)] = v;
}

// marco de grosor t alrededor de una caja en el plano XY, de z0 a z1
function frame(x0, x1, y0, y1, t, z0, z1, v) {
    for (let y = y0; y <= y1; y++)
        for (let x = x0; x <= x1; x++)
            if (x - x0 < t || x1 - x < t || y - y0 < t || y1 - y < t) box(x, x, y, y, z0, z1, v);
}

const radius = (x, y) => Math.hypot(x + 0.5 - C, y + 0.5 - C);

// 1. base de hormigón y suelo de placas a FLOOR_Z
box(0, G - 1, 0, G - 1, 0, FLOOR_Z - 1, V.BASE);
box(0, G - 1, 0, G - 1, FLOOR_Z, FLOOR_Z, V.FLOOR);

// 2. muralla exterior de placas, 4 celdas de grosor y 22 de alto
frame(0, G - 1, 0, G - 1, 4, FLOOR_Z + 1, 27, V.PLATE);
frame(0, G - 1, 0, G - 1, 4, 0, FLOOR_Z, V.BASE);

// 3. plaza: anillo de luz en el suelo y obelisco central
for (let y = 0; y < G; y++)
    for (let x = 0; x < G; x++) {
        const r = radius(x, y);
        if (r >= 30 && r < 31 && r < PLAZA_R) box(x, x, y, y, FLOOR_Z, FLOOR_Z, V.GLOW);
        if (r < 4.5) box(x, x, y, y, FLOOR_Z + 1, 30, V.PANEL);
    }

// 4. escaleras en cruz (cuatro brazos de 6 celdas) y anillo elevado con base de hormigón
for (let y = 0; y < G; y++)
    for (let x = 0; x < G; x++) {
        const r = radius(x, y), dx = Math.abs(x + 0.5 - C), dy = Math.abs(y + 0.5 - C);
        if (r >= PLAZA_R && r < RING_R0 && (dx <= 3 || dy <= 3)) {
            const j = Math.floor((r - PLAZA_R) / 4);      // escalón 0..5, subida de 1 celda cada 4
            box(x, x, y, y, FLOOR_Z + 1, FLOOR_Z + 1 + j, V.METAL);
            box(x, x, y, y, 0, FLOOR_Z, V.BASE);
        }
        if (r >= RING_R0 && r < RING_R1) {
            box(x, x, y, y, 0, RING_TOP - 1, V.BASE);
            box(x, x, y, y, RING_TOP, RING_TOP, V.METAL);
        }
    }
// barandillas exteriores del anillo, de 2 celdas de alto
for (let y = 0; y < G; y++)
    for (let x = 0; x < G; x++) {
        const r = radius(x, y);
        if (r >= RING_R1 - 1 && r < RING_R1) box(x, x, y, y, RING_TOP + 1, RING_TOP + 2, V.PANEL);
    }

// 5. búnkeres de esquina: muros de placa, tejado con claraboya y puerta hacia la plaza
for (const [x0, y0, door] of BUNKERS) {
    const x1 = x0 + BUNKER - 1, y1 = y0 + BUNKER - 1;
    const ceil = 24;
    frame(x0, x1, y0, y1, 3, FLOOR_Z + 1, ceil - 1, V.PLATE);
    box(x0 + 3, x1 - 3, y0 + 3, y1 - 3, FLOOR_Z + 1, ceil - 1, V.AIR);
    box(x0, x1, y0, y1, ceil, ceil + 1, V.PANEL);
    box(x0 + 16, x0 + 23, y0 + 16, y0 + 23, ceil, ceil + 1, V.AIR);
    const yd0 = y0 + 17, yd1 = y0 + 22;
    if (door === 'E') box(x1 - 2, x1, yd0, yd1, FLOOR_Z + 1, FLOOR_Z + 8, V.AIR);
    else box(x0, x0 + 2, yd0, yd1, FLOOR_Z + 1, FLOOR_Z + 8, V.AIR);
    for (const [px, py] of [[8, 8], [28, 8], [8, 28], [28, 28]]) box(x0 + px, x0 + px + 2, y0 + py, y0 + py + 2, FLOOR_Z + 1, ceil - 1, V.PLATE);
    box(x0 + 12, x0 + 12, y0 + 12, y0 + 12, FLOOR_Z + 1, ceil - 1, V.GLOW);
}

// ---- entidades (coordenadas en unidades: celda * CELL + CELL/2)
const ents = [];
const unit = (c) => c * CELL + CELL / 2;
const add = (type, x, y, z, a = []) => ents.push({ type, o: [x, y, z], a: [...a, 0, 0, 0, 0, 0].slice(0, 5) });
const FEET_GROUND = (FLOOR_Z + 1) * CELL;
const FEET_RING = (RING_TOP + 1) * CELL;

// celda pisable (suelo o anillo) con 3 celdas libres encima
function freeSpot(x, y, top) {
    if (get(x, y, top) !== V.FLOOR && get(x, y, top) !== V.METAL) return false;
    for (let z = top + 1; z <= top + 3; z++) if (get(x, y, z) !== V.AIR) return false;
    return true;
}
const yawToCenter = (x, y) => {
    const ux = C - x, uy = C - y, n = Math.hypot(ux, uy) || 1;
    return Math.round((Math.atan2(-ux / n, uy / n) * 180 / Math.PI + 360) % 360);
};

// salidas: 2 en cada búnker, 4 en la plaza y 4 en el anillo
const spawnCells = [];
for (const [x0, y0] of BUNKERS) spawnCells.push([x0 + 12, y0 + 30], [x0 + 30, y0 + 10]);
for (const a of [0, 90, 180, 270]) spawnCells.push([Math.round(C + 22 * Math.cos(a * Math.PI / 180)), Math.round(C + 22 * Math.sin(a * Math.PI / 180))]);
for (const a of [45, 135, 225, 315]) spawnCells.push([Math.round(C + 64 * Math.cos(a * Math.PI / 180)), Math.round(C + 64 * Math.sin(a * Math.PI / 180))]);
for (const [x, y] of spawnCells) {
    const top = radius(x, y) >= RING_R0 && radius(x, y) < RING_R1 ? RING_TOP : FLOOR_Z;
    const feet = top === RING_TOP ? FEET_RING : FEET_GROUND;
    add(ET.PLAYERSTART, unit(x), unit(y), feet, [yawToCenter(x, y), 0, 0, 0, 0]);
}

// objetos: cuádruple daño sobre la plaza y el resto repartido por suelo y anillo
add(ET.QUADDAMAGE, unit(C), unit(C + 20), FEET_GROUND + 2);
const itemCycle = [ET.SHELLS, ET.BULLETS, ET.ROCKETS, ET.HEALTH, ET.RIFLEROUNDS, ET.GRENADES,
    ET.CARTRIDGES, ET.HEALTHBOOST, ET.GREENARMOUR, ET.YELLOWARMOUR];
for (let t = 0, n = 0; t < 40000 && n < 96; t++) {
    const x = ri(6, G - 7), y = ri(6, G - 7), r = radius(x, y);
    let top = -1;
    if (r >= RING_R0 && r < RING_R1) top = RING_TOP;
    else if (r >= PLAZA_R + 2 && r < 110 && !(Math.abs(x + 0.5 - C) <= 3 || Math.abs(y + 0.5 - C) <= 3) && !inBunker(x, y)) top = FLOOR_Z;
    else if (r < PLAZA_R && r > 6) top = FLOOR_Z;
    if (top < 0 || !freeSpot(x, y, top)) continue;
    if (inBunker(x, y)) continue;
    add(itemCycle[n % itemCycle.length], unit(x), unit(y), (top + 1) * CELL + 2);
    n++;
}
function inBunker(x, y) {
    return BUNKERS.some(([x0, y0]) => x >= x0 - 1 && x <= x0 + BUNKER && y >= y0 - 1 && y <= y0 + BUNKER);
}

// luces: anillo de neón alrededor de la plaza, una en cada búnker y cuatro en el anillo
for (let i = 0; i < 12; i++) {
    const a = (i / 12) * Math.PI * 2;
    add(ET.LIGHT, unit(C + Math.cos(a) * 30), unit(C + Math.sin(a) * 30), 80, [240, 120, 210, 255]);
}
for (const [x0, y0] of BUNKERS) add(ET.LIGHT, unit(x0 + 20), unit(y0 + 20), 150, [260, 150, 220, 255]);
for (const a of [45, 135, 225, 315]) add(ET.LIGHT, unit(C + 64 * Math.cos(a * Math.PI / 180)), unit(C + 64 * Math.sin(a * Math.PI / 180)), 120, [200, 110, 200, 255]);

// ---- escritura binaria (little endian, como savec/save_world)
class Writer {
    constructor() { this.buf = Buffer.alloc(1 << 24); this.n = 0; }
    ensure(k) {
        if (this.n + k <= this.buf.length) return;
        const nb = Buffer.alloc(Math.max(this.buf.length * 2, this.n + k));
        this.buf.copy(nb, 0, 0, this.n);
        this.buf = nb;
    }
    u8(v) { this.ensure(1); this.buf[this.n++] = v & 0xFF; }
    u16(v) { this.ensure(2); this.buf.writeUInt16LE(v & 0xFFFF, this.n); this.n += 2; }
    i16(v) { this.ensure(2); this.buf.writeInt16LE(v, this.n); this.n += 2; }
    i32(v) { this.ensure(4); this.buf.writeInt32LE(v, this.n); this.n += 4; }
    f32(v) { this.ensure(4); this.buf.writeFloatLE(v, this.n); this.n += 4; }
    str(s) { this.ensure(s.length); this.buf.write(s, this.n, 'latin1'); this.n += s.length; }
    bytes() { return this.buf.subarray(0, this.n); }
}

const w = new Writer();
let leaves = 0;

// región uniforme -> código; si no lo es, -1
function uniform(x, y, z, s) {
    const v = grid[at(x, y, z)];
    for (let k = z; k < z + s; k++)
        for (let j = y; j < y + s; j++)
            for (let i = x; i < x + s; i++) if (grid[at(i, j, k)] !== v) return -1;
    return v;
}

// formato de cubo hoja: flags y 6 texturas, también en los vacíos (savec en worldio.cpp)
function leaf(v) {
    leaves++;
    w.u8(v === V.AIR ? OCTSAV_EMPTY : OCTSAV_SOLID);
    for (let f = 0; f < 6; f++) w.u16(SLOT[v]);
}

// octante i: x en bit 0, y en bit 1, z en bit 2 (ivec(i, co, size) en shared/geom.h)
function emit(x, y, z, s) {
    const v = uniform(x, y, z, s);
    if (v >= 0) { leaf(v); return; }
    w.u8(OCTSAV_CHILDREN);
    const h = s >> 1;
    for (let i = 0; i < 8; i++) emit(x + (i & 1) * h, y + ((i >> 1) & 1) * h, z + ((i >> 2) & 1) * h, h);
}

// cabecera octaheader: 4 bytes de magia + 9 enteros
w.str('OCTA');
w.i32(MAPVERSION); w.i32(40); w.i32(WORLD); w.i32(ents.length);
w.i32(0); w.i32(0); w.i32(0); w.i32(0); w.i32(0);
// nombre del juego, datos de entidad y de juego (vacíos), MRU de texturas (vacío)
w.u8(3); w.str('fps\0');
w.u16(0); w.u16(0); w.u16(0);
// entidades: vec o, attr1..5, type, reserved (24 bytes)
for (const e of ents) {
    e.o.forEach((v) => w.f32(v));
    e.a.forEach((v) => w.i16(v));
    w.u8(e.type); w.u8(0);
}
// vslots: ninguno. octree: los 8 octantes raíz, cada uno de WORLD/2 unidades
for (let i = 0; i < 8; i++) emit((i & 1) * (G / 2), ((i >> 1) & 1) * (G / 2), ((i >> 2) & 1) * (G / 2), G / 2);

// --preview solo escribe la miniatura: no toca el mapa horneado ni su PVS
if (!opt('--preview')) {
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'scifi.ogz'), zlib.gzipSync(w.bytes()));
}

// ---- cfg: texturas, cielo y niebla de la ciudadela
const cfg = `// scifi.cfg generado por tools/desktop/gen-scifi-map.mjs (SauVREngine).
// Ciudadela de metal y neón: plaza con obelisco, anillo elevado y cuatro búnkeres de esquina.
// Se ejecuta después de data/default_map_settings.cfg.

skybox "skyboxes/turbulent"
fog 2400
fogcolour 0x0A1424
ambient 0x2C3A52

texturereset
    setshader "stdworld"
        texture 0 "textures/sky.png"                       // [0] cielo fijo
        texture 0 "textures/default.png"                   // [1] textura por defecto
    setshader bumpworld
        texture 0 "ikbase/ik_floor_conc128b.jpg"           // [2] hormigón de la base
        texture n "ikbase/ik_floor_conc128b_n.png"
        texture 0 "evil_textures/e7dimfloor.jpg"           // [3] suelo de placas
        texture n "evil_textures/e7dimfloor_NRM.jpg"
        texture 0 "mitaman/mm-metalbase1.jpg"              // [4] placas de muro
        texture n "mitaman/mm-metalbase1_n.png"
        texture 0 "tech1soc/032-15a.jpg"                   // [5] paneles de techo y obelisco
        texture n "tech1soc/032-15a_n.png"
        texture 0 "textures/yves_allaire/e7/e7sbrickfloor_jump_red_glow.jpg" // [6] franja de neón
        texture n "tech1soc/matbrown_lgt2_n.png"
        texture 0 "textures/medieval_soc/metal2.jpg"       // [7] metal de anillo y escaleras
        texture n "textures/medieval_soc/metal2_n.png"
`;
if (!opt('--preview')) fs.writeFileSync(path.join(outDir, 'scifi.cfg'), cfg);

if (!opt('--preview')) console.log(`scifi: ${ents.length} entidades, ${leaves} hojas del octree, ${w.n} bytes sin comprimir, mundo ${WORLD}`);

// ---- miniatura opcional (--preview ruta.png): vista cenital 512x512, norte arriba.
// El menú de mapas usa packages/base/<mapa>.jpg; la conversión a jpg se hace aparte (System.Drawing).
const previewPath = opt('--preview');
if (previewPath) {
    const size = 512, rgb = Buffer.alloc(size * size * 3);
    const colour = { [V.BASE]: [90, 96, 104], [V.FLOOR]: [70, 84, 98], [V.PLATE]: [120, 128, 140],
        [V.PANEL]: [60, 70, 90], [V.GLOW]: [255, 90, 160], [V.METAL]: [150, 160, 176] };
    for (let py = 0; py < size; py++)
        for (let px = 0; px < size; px++) {
            const x = Math.floor(px * G / size), y = Math.floor((size - 1 - py) * G / size);
            let top = -1, c = [8, 12, 20];
            for (let z = G - 1; z >= 0 && top < 0; z--) if (get(x, y, z) !== V.AIR) { top = z; c = colour[get(x, y, z)]; }
            const shade = top < 0 ? 1 : 0.55 + 0.45 * (top / 30);
            rgb.set(c.map((v) => Math.min(255, Math.round(v * shade))), (py * size + px) * 3);
        }
    fs.writeFileSync(previewPath, encodePng(size, rgb));
}

function encodePng(size, rgb) {
    const CRC = Array.from({ length: 256 }, (_, n) => {
        let c = n;
        for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
        return c >>> 0;
    });
    const crc32 = (buf) => {
        let c = 0xFFFFFFFF;
        for (const b of buf) c = CRC[(c ^ b) & 0xFF] ^ (c >>> 8);
        return (c ^ 0xFFFFFFFF) >>> 0;
    };
    const chunk = (type, data) => {
        const len = Buffer.alloc(4), crc = Buffer.alloc(4);
        len.writeUInt32BE(data.length);
        const td = Buffer.concat([Buffer.from(type, 'latin1'), data]);
        crc.writeUInt32BE(crc32(td));
        return Buffer.concat([len, td, crc]);
    };
    const raw = Buffer.alloc((size * 3 + 1) * size);
    for (let y = 0; y < size; y++) rgb.copy(raw, y * (size * 3 + 1) + 1, y * size * 3, (y + 1) * size * 3);
    const ihdr = Buffer.alloc(13);
    ihdr.writeUInt32BE(size, 0); ihdr.writeUInt32BE(size, 4);
    ihdr[8] = 8; ihdr[9] = 2;
    return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr),
        chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}
