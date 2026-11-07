# Convierte un personaje GLB con rig de Mixamo en un modelo md5 que hereda las
# animaciones y el ragdoll de mrfixit sin deformar la malla.
#
#   blender -b --factory-startup -P tools/blender/glb2md5.py -- \
#       --glb modelo.glb --ref .../mrfixit/mrfixit.md5mesh --out .../models/soldado \
#       [--name soldado] [--icons .../packages/icons] [--smooth 80] [--mdlscale 800]
#
# La malla se deja tal cual (solo se orienta y se escala a la altura de
# mrfixit). Lo que cambia es el esqueleto: los 75 joints de mrfixit, con sus
# mismas orientaciones, se colocan en las articulaciones del modelo nuevo. Las
# animaciones de mrfixit se retargetean a ese esqueleto conservando las
# rotaciones y cambiando solo las traslaciones (longitudes de hueso), y las
# manos, que en mrfixit cuelgan de una cadena IK aparte (ArmIK -> HandGoal), se
# recolocan en cada frame al final del antebrazo. El modelo usa su propio
# esqueleto, sus propias animaciones y su propio ragdoll.
import bpy, sys, os, re, math, argparse
import numpy as np

def parse_args():
    argv = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True)
    ap.add_argument("--ref", required=True, help="md5mesh cuyo esqueleto y animaciones se heredan (mrfixit)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default=None)
    ap.add_argument("--texsize", type=int, default=1024)
    ap.add_argument("--icons", default=None, help="carpeta packages/icons donde dejar los retratos del menú")
    ap.add_argument("--smooth", type=float, default=80, help="ángulo de suavizado de normales para md5load (0 = facetado)")
    ap.add_argument("--mdlscale", type=float, default=800, help="mdlscale del md5.cfg (mrfixit usa 800)")
    return ap.parse_args(argv)

# ---------- cuaterniones (x, y, z, w), convenio md5: w <= 0 ----------

def quat_w(x, y, z):
    t = 1.0 - x*x - y*y - z*z
    return 0.0 if t < 0 else -math.sqrt(t)

def qrot(q, v):
    u = np.array(q[:3]); w = q[3]
    return v + 2.0*np.cross(u, np.cross(u, v) + w*v)

def qconj(q):
    return (-q[0], -q[1], -q[2], q[3])

def qmul(a, b):
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return (aw*bx + ax*bw + ay*bz - az*by,
            aw*by - ax*bz + ay*bw + az*bx,
            aw*bz + ax*by - ay*bx + az*bw,
            aw*bw - ax*bx - ay*by - az*bz)

def floats(s):
    return [float(x) for x in s.replace("(", " ").replace(")", " ").split()]

# ---------- md5 de referencia ----------

def load_ref(path):
    joints, lines = [], open(path).read().splitlines()
    i, verts_all, tris_all = 0, [], []
    while i < len(lines):
        l = lines[i].strip()
        if l.startswith("joints {"):
            i += 1
            while not lines[i].strip().startswith("}"):
                s = lines[i].split("//")[0].replace("(", " ").replace(")", " ").split()
                qx, qy, qz = (float(x) for x in s[5:8])
                joints.append(dict(name=s[0].strip('"'), parent=int(s[1]),
                                   pos=np.array([float(x) for x in s[2:5]]), q=(qx, qy, qz, quat_w(qx, qy, qz))))
                i += 1
        elif l.startswith("mesh {"):
            vs, ts, ws = {}, [], {}
            i += 1
            while not lines[i].strip().startswith("}"):
                s = lines[i].replace("(", " ").replace(")", " ").split()
                if s and s[0] == "vert": vs[int(s[1])] = (int(s[4]), int(s[5]))
                elif s and s[0] == "tri": ts.append((int(s[2]), int(s[3]), int(s[4])))
                elif s and s[0] == "weight": ws[int(s[1])] = (int(s[2]), float(s[3]), np.array([float(x) for x in s[4:7]]))
                i += 1
            base = len(verts_all)
            for vi in range(len(vs)):
                st, cnt = vs[vi]; p = np.zeros(3)
                for wi in range(st, st+cnt):
                    j, b, wp = ws[wi]; jt = joints[j]
                    p += b*(jt["pos"] + qrot(jt["q"], wp))
                verts_all.append(p)
            tris_all += [(a+base, b+base, c+base) for a, b, c in ts]
        i += 1
    return joints, np.array(verts_all), tris_all

def signed_volume(verts, tris):
    return sum(np.dot(verts[a], np.cross(verts[b], verts[c])) for a, b, c in tris)

# ---------- correspondencia Mixamo <-> mrfixit ----------

MX = "mixamorig:"
FINGERS = {  # dedo Mixamo -> sufijo de la cadena de mrfixit, por lado
    "L": {"Index": ".L", "Middle": ".L.001", "Ring": ".L.002", "Thumb": ".L.003"},
    "R": {"Index": ".R.001", "Middle": ".R.002", "Ring": ".R", "Thumb": ".R.003"},
}

def finger_joint(side, finger, n):
    return "Finger%d%s" % (n, FINGERS[side][finger])

def build_posmap():
    # joint de mrfixit -> articulación Mixamo donde se coloca
    m = {"Hips": "Hips", "Spine1": "Spine", "Spine2": "Spine2", "Neck": "Neck", "Head": "Head"}
    for side, full in (("L", "Left"), ("R", "Right")):
        m["UpperArm."+side] = full+"Arm"
        m["LowerArm."+side] = full+"ForeArm"
        m["Hand."+side] = full+"Hand"
        m["HandGoal."+side] = full+"Hand"
        m["Thigh."+side] = full+"UpLeg"
        m["Shin."+side] = full+"Leg"
        m["UpperFoot."+side] = full+"Foot"
        m["LowerFoot."+side] = full+"ToeBase"
        for f in ("Index", "Middle", "Ring", "Thumb"):
            for n in (1, 2, 3):
                m[finger_joint(side, f, n)] = "%sHand%s%d" % (full, f, n)
    return m

def build_weightmap():
    # hueso Mixamo -> joint de mrfixit que recibe sus pesos
    m = {"Hips": "Hips", "Spine": "Spine1", "Spine1": "Spine1", "Spine2": "Spine2",
         "Neck": "Neck", "Head": "Head", "HeadTop_End": "Head"}
    for side, full in (("L", "Left"), ("R", "Right")):
        m[full+"Shoulder"] = "Spine2"
        m[full+"Arm"] = "UpperArm."+side
        m[full+"ForeArm"] = "LowerArm."+side
        m[full+"Hand"] = "HandGoal."+side
        m[full+"UpLeg"] = "Thigh."+side
        m[full+"Leg"] = "Shin."+side
        m[full+"Foot"] = "UpperFoot."+side
        m[full+"ToeBase"] = "LowerFoot."+side
        m[full+"Toe_End"] = "LowerFoot."+side
        for f, dst in (("Index", "Index"), ("Middle", "Middle"), ("Ring", "Ring"), ("Pinky", "Ring"), ("Thumb", "Thumb")):
            for n in (1, 2, 3, 4):
                m["%sHand%s%d" % (full, f, n)] = finger_joint(side, dst, min(n, 3))
    return m

def normalize(v):
    n = np.linalg.norm(v)
    return v/n if n > 1e-9 else v

# ---------- animaciones ----------

def load_anim(path):
    lines = open(path).read().splitlines()
    hier, base, frames, bounds, head = [], [], {}, [], []
    i = 0
    while i < len(lines):
        l = lines[i].strip()
        if l.startswith("hierarchy {"):
            i += 1
            while not lines[i].strip().startswith("}"):
                s = lines[i].split("//")[0].split()
                hier.append((s[0].strip('"'), int(s[1]), int(s[2]), int(s[3]))); i += 1
        elif l.startswith("bounds {"):
            i += 1
            while not lines[i].strip().startswith("}"):
                bounds.append(lines[i]); i += 1
        elif l.startswith("baseframe {"):
            i += 1
            while not lines[i].strip().startswith("}"):
                base.append(floats(lines[i])); i += 1
        elif l.startswith("frame "):
            n, data = int(l.split()[1]), []
            i += 1
            while not lines[i].strip().startswith("}"):
                data += floats(lines[i]); i += 1
            frames[n] = data
        elif l and not l.startswith(("numAnimatedComponents", "}")):
            head.append(lines[i])
        i += 1
    return dict(head=head, hier=hier, base=base, bounds=bounds, frames=[frames[k] for k in sorted(frames)])

def decode_frame(anim, data):
    local = []
    for (name, parent, flags, start), b in zip(anim["hier"], anim["base"]):
        v, k = list(b), 0
        for c in range(6):
            if flags & (1 << c): v[c] = data[start+k]; k += 1
        local.append((np.array(v[:3]), (v[3], v[4], v[5], quat_w(v[3], v[4], v[5]))))
    return local

def fk(hier, local):
    wp, wq = [], []
    for (name, parent, _, _), (t, q) in zip(hier, local):
        if parent < 0: wp.append(t); wq.append(q)
        else: wp.append(wp[parent] + qrot(wq[parent], t)); wq.append(qmul(wq[parent], q))
    return wp, wq

def retarget_anim(src_path, dst_path, joints, newpos):
    anim = load_anim(src_path)
    hier = anim["hier"]
    idx = {h[0]: n for n, h in enumerate(hier)}
    old = [j["pos"] for j in joints]
    # cambio de la traslación local de cada joint, en el espacio de su padre
    delta = []
    for n, (name, parent, _, _) in enumerate(hier):
        if parent < 0: delta.append(newpos[n] - old[n])
        else: delta.append(qrot(qconj(joints[parent]["q"]), (newpos[n]-newpos[parent]) - (old[n]-old[parent])))
    hipscale = newpos[0][2] / old[0][2]
    goals = [(idx["HandGoal."+s], idx["Hand."+s], hier[idx["HandGoal."+s]][1]) for s in ("L", "R")]

    def convert(local):
        orig_p, _ = fk(hier, local)
        new = []
        for n, (t, q) in enumerate(local):
            if n == 0:  # raíz: la altura escala con la cadera, para tumbarse y saltar igual
                t = np.array([t[0]+delta[0][0], t[1]+delta[0][1], t[2]*hipscale])
            else:
                t = t + delta[n]
            new.append((t, q))
        new_p, new_q = fk(hier, new)
        for goal, hand, parent in goals:
            target = new_p[hand] + (orig_p[goal] - orig_p[hand])
            new[goal] = (qrot(qconj(new_q[parent]), target - new_p[parent]), new[goal][1])
        return new

    def fmt(local):
        return ["\t( %f %f %f ) ( %f %f %f )" % (t[0], t[1], t[2], q[0], q[1], q[2]) for t, q in local]

    out = anim["head"] + ["numAnimatedComponents %d" % (6*len(hier)), "", "hierarchy {"]
    out += ['\t"%s"\t%d 63 %d\t//' % (name, parent, 6*n) for n, (name, parent, _, _) in enumerate(hier)]
    out += ["}", "", "bounds {"] + anim["bounds"] + ["}", "", "baseframe {"]
    out += fmt(convert(decode_frame(anim, anim["frames"][0])))
    out += ["}", ""]
    for n, data in enumerate(anim["frames"]):
        local = convert(decode_frame(anim, data))
        out += ["frame %d {" % n] + ["\t%f %f %f %f %f %f" % (t[0], t[1], t[2], q[0], q[1], q[2]) for t, q in local] + ["}", ""]
    open(dst_path, "w").write("\n".join(out))

# ---------- ragdoll ----------

def retarget_ragdoll(src_path, dst_path, joints, newpos):
    old = np.array([j["pos"] for j in joints]); newpos = np.array(newpos)
    verts_old, verts_new, out = [], [], []
    for l in open(src_path).read().splitlines():
        s = l.split()
        if s and s[0] == "rdvert":
            p = np.array([float(x) for x in s[1:4]])
            near = np.argmin(np.linalg.norm(old - p, axis=1))
            q = p + newpos[near] - old[near]
            verts_old.append(p); verts_new.append(q)
            l = "rdvert %f %f %f" % tuple(q) + (" " + " ".join(s[4:]) if len(s) > 4 else "")
        elif s and s[0] == "rdlimitdist":
            a, b = int(s[1]), int(s[2])
            k = np.linalg.norm(verts_new[a]-verts_new[b]) / max(np.linalg.norm(verts_old[a]-verts_old[b]), 1e-6)
            l = "rdlimitdist %d %d %s" % (a, b, " ".join("%f" % (float(x)*k) for x in s[3:]))
        out.append(l)
    open(dst_path, "w").write("\n".join(out) + "\n")

# ---------- conversión ----------

def main():
    args = parse_args()
    name = args.name or os.path.basename(os.path.normpath(args.out))
    os.makedirs(args.out, exist_ok=True)
    ref_dir = os.path.dirname(os.path.abspath(args.ref))

    joints, ref_verts, ref_tris = load_ref(args.ref)
    jidx = {j["name"]: i for i, j in enumerate(joints)}
    ref_sign = np.sign(signed_volume(ref_verts, ref_tris))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=args.glb)
    arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    # el importador añade una Icosphere como forma de los huesos: nos quedamos
    # con la malla pesada al armature
    mesh = max((o for o in bpy.context.scene.objects if o.type == "MESH" and o.vertex_groups),
               key=lambda o: len(o.data.vertices))

    # Los GLB de Tripo traen cada triángulo con sus propios vértices (sombreado
    # plano). Se sueldan por posición para que el motor pueda promediar las
    # normales; las costuras de UV siguen partidas más abajo, en la misma posición.
    import bmesh
    bm = bmesh.new(); bm.from_mesh(mesh.data)
    nv = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    print("glb2md5: soldados %d vértices duplicados" % (nv - len(bm.verts)))
    bm.to_mesh(mesh.data); bm.free()

    bones = {b.name[len(MX):]: b for b in arm.data.bones if b.name.startswith(MX)}
    src = {n: np.array(arm.matrix_world @ b.head_local) for n, b in bones.items()}

    me = mesh.data
    mw = np.array(mesh.matrix_world)
    co = np.array([v.co for v in me.vertices])
    co = (np.c_[co, np.ones(len(co))] @ mw.T)[:, :3]

    # Orientación y escala globales: el modelo pasa a mirar a +x, con su
    # izquierda en +y y la altura de mrfixit. Es la única transformación que
    # recibe la malla.
    up = normalize(src["Neck"] - src["Hips"])
    left = src["LeftArm"] - src["RightArm"]
    left = normalize(left - up*np.dot(left, up))
    fwd = np.cross(left, up)
    G = np.vstack([fwd, left, up])
    h_src = (co @ up).max() - (co @ up).min()
    h_ref = ref_verts[:, 2].max() - ref_verts[:, 2].min()
    s = h_ref / h_src
    toe = np.dot(src["LeftToeBase"] - src["LeftFoot"], fwd)
    print("glb2md5: escala %.3f, pies hacia delante: %s" % (s, toe > 0))
    hips_ref = joints[jidx["Hips"]]["pos"]
    floor_src = np.array([np.dot(src["Hips"], fwd), np.dot(src["Hips"], left), (co @ up).min()])
    floor_ref = np.array([hips_ref[0], hips_ref[1], ref_verts[:, 2].min()])
    to_ref = lambda p: s*(G @ p - floor_src) + floor_ref
    src = {n: to_ref(p) for n, p in src.items()}
    co = np.array([to_ref(p) for p in co])

    # Esqueleto nuevo: los joints con pareja Mixamo van a su articulación; el
    # resto (raíz, cadenas IK, nulos de los dedos, el tag del arma) se desplaza
    # igual que el joint con pareja más cercano.
    posmap = build_posmap()
    old = np.array([j["pos"] for j in joints])
    newpos = [None]*len(joints)
    for n, j in enumerate(joints):
        if j["name"] in posmap and posmap[j["name"]] in src: newpos[n] = src[posmap[j["name"]]]
    mapped = [n for n in range(len(joints)) if newpos[n] is not None]
    for n in range(len(joints)):
        if newpos[n] is None:
            near = min(mapped, key=lambda m: np.linalg.norm(old[m]-old[n]))
            newpos[n] = old[n] + newpos[near] - old[near]

    # Pesos por vértice, traducidos a joints de mrfixit.
    gname = {g.index: g.name[len(MX):] for g in mesh.vertex_groups if g.name.startswith(MX)}
    wmap = build_weightmap()
    vw = []
    for v in me.vertices:
        acc = {}
        for g in v.groups:
            if g.group in gname and g.weight > 1e-4:
                jn = wmap.get(gname[g.group], "Hips"); acc[jn] = acc.get(jn, 0.0) + g.weight
        top = sorted(acc.items(), key=lambda x: -x[1])[:4]
        top = [x for x in top if x[1] >= 0.01] or top[:1] or [("Hips", 1.0)]
        tot = sum(w for _, w in top)
        vw.append([(jn, w/tot) for jn, w in top])
    missing = sorted({gname[g] for g in gname} - set(wmap))
    if missing: print("glb2md5: huesos sin destino, van a Hips:", missing)

    # Vértices md5: uno por (vértice, uv); triángulos con el sentido de mrfixit.
    me.calc_loop_triangles()
    uvl = me.uv_layers.active.data
    key2idx, mdverts, mdtris = {}, [], []
    for t in me.loop_triangles:
        tri = []
        for li in t.loops:
            vi = me.loops[li].vertex_index
            u, v = uvl[li].uv
            key = (vi, round(u, 5), round(v, 5))
            if key not in key2idx:
                key2idx[key] = len(mdverts); mdverts.append((vi, u, 1.0-v))
            tri.append(key2idx[key])
        mdtris.append(tri)
    pos = np.array([co[vi] for vi, _, _ in mdverts])
    if np.sign(signed_volume(pos, mdtris)) != ref_sign:
        mdtris = [[a, c, b] for a, b, c in mdtris]

    # Textura (con variantes azul y roja).
    img = next((n.image for m in me.materials if m and m.use_nodes for n in m.node_tree.nodes if n.type == "TEX_IMAGE" and n.image), None) \
        or next((im for im in bpy.data.images if im.size[0] > 0), None)
    skins = {}
    if img:
        if max(img.size) > args.texsize: img.scale(args.texsize, args.texsize)
        px = np.array(img.pixels[:]).reshape(-1, 4)
        lum = (px[:, :3] @ np.array([0.3, 0.59, 0.11]))[:, None]
        for suffix, team in (("", None), ("_b", (0.35, 0.55, 1.0)), ("_r", (1.0, 0.35, 0.3))):
            out = px.copy()
            if team: out[:, :3] = 0.55*px[:, :3] + 0.45*lum*np.array(team)*1.6
            im = bpy.data.images.new(name+suffix, img.size[0], img.size[1])
            im.pixels = np.clip(out, 0, 1).ravel().tolist()
            im.file_format = "JPEG"
            im.save(filepath=os.path.abspath(os.path.join(args.out, name+suffix+".jpg")), quality=90)
            skins[suffix] = name+suffix+".jpg"

    # md5mesh con el esqueleto nuevo (mismas orientaciones que mrfixit).
    lines = ["MD5Version 10", 'commandline "glb2md5 %s"' % os.path.basename(args.glb), "",
             "numJoints %d" % len(joints), "numMeshes 1", "", "joints {"]
    for n, j in enumerate(joints):
        p, q = newpos[n], j["q"]
        lines.append('\t"%s"\t%d ( %f %f %f ) ( %f %f %f )\t\t// %s' % (j["name"], j["parent"], p[0], p[1], p[2], q[0], q[1], q[2],
                                                                         joints[j["parent"]]["name"] if j["parent"] >= 0 else ""))
    lines += ["}", "", "mesh {", "\t// meshes: %s" % name, '\tshader "%s"' % skins.get("", name), "", "\tnumverts %d" % len(mdverts)]
    weights = []
    for i, (vi, u, v) in enumerate(mdverts):
        lines.append("\tvert %d ( %f %f ) %d %d" % (i, u, v, len(weights), len(vw[vi])))
        for jn, w in vw[vi]:
            jt = jidx[jn]
            weights.append((jt, w, qrot(qconj(joints[jt]["q"]), pos[i]-newpos[jt])))
    lines += ["", "\tnumtris %d" % len(mdtris)]
    lines += ["\ttri %d %d %d %d" % (i, a, b, c) for i, (a, b, c) in enumerate(mdtris)]
    lines += ["", "\tnumweights %d" % len(weights)]
    lines += ["\tweight %d %d %f ( %f %f %f )" % (i, j, b, p[0], p[1], p[2]) for i, (j, b, p) in enumerate(weights)]
    lines += ["}", ""]
    open(os.path.join(args.out, name+".md5mesh"), "w").write("\n".join(lines))

    # Animaciones y ragdoll retargeteados al esqueleto nuevo.
    ref_name = os.path.basename(ref_dir)
    anims_cfg = open(os.path.join(ref_dir, "anims.cfg")).read()
    for f in sorted(set(re.findall(r'"([^"]+\.md5anim)"', anims_cfg))):
        retarget_anim(os.path.join(ref_dir, f), os.path.join(args.out, f), joints, newpos)
    open(os.path.join(args.out, "anims.cfg"), "w").write(anims_cfg.replace('md5dir "%s"' % ref_name, 'md5dir "%s"' % name))
    retarget_ragdoll(os.path.join(ref_dir, "ragdoll.cfg"), os.path.join(args.out, "ragdoll.cfg"), joints, newpos)

    def cfg(skin, md5dir=None):
        c = ['md5dir "%s"' % md5dir] if md5dir else []
        c += ['md5load "%s.md5mesh" %s %g' % (name, name, args.smooth),
              'exec "packages/models/%s/ragdoll.cfg"' % name,
              "md5tag Weapon tag_weapon",
              'md5skin %s "%s"' % (name, skin),
              'exec "packages/models/%s/anims.cfg"' % name,
              "mdlscale %g" % args.mdlscale, "mdlspec 50", ""]
        return "\n".join(c)
    open(os.path.join(args.out, "md5.cfg"), "w").write(cfg(skins.get("", "")))
    for team, suffix in (("blue", "_b"), ("red", "_r")):
        os.makedirs(os.path.join(args.out, team), exist_ok=True)
        open(os.path.join(args.out, team, "md5.cfg"), "w").write(cfg(skins.get(suffix, ""), name))
    print("glb2md5: %d vertices, %d triángulos, %d pesos -> %s" % (len(mdverts), len(mdtris), len(weights), args.out))
    if args.icons and img:
        render_icons(mesh, co, newpos[jidx["Head"]], newpos[jidx["Neck"]], args.out, args.icons, name, skins)

def render_icons(mesh, co, headpos, neckpos, outdir, icondir, name, skins):
    # Retratos de 64x64 para el menú de modelos: la malla ya en el espacio de
    # mrfixit, vista de frente a la altura del pecho, una por cada textura.
    for o in list(bpy.context.scene.objects):
        if o != mesh: bpy.data.objects.remove(o)
    mesh.modifiers.clear(); mesh.parent = None; mesh.matrix_world.identity()
    for v, p in zip(mesh.data.vertices, co): v.co = p
    mat = mesh.data.materials[0]
    tex = next(n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE")
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "STUDIO"; sc.display.shading.color_type = "TEXTURE"
    sc.render.resolution_x = sc.render.resolution_y = 64
    sc.render.image_settings.file_format = "JPEG"
    sc.world = bpy.data.worlds.new("icono"); sc.world.color = (0.12, 0.12, 0.14)
    cam = bpy.data.cameras.new("icono"); cam.type = "ORTHO"; cam.ortho_scale = 3.6
    camo = bpy.data.objects.new("icono", cam); sc.collection.objects.link(camo); sc.camera = camo
    head = (headpos + neckpos) / 2
    camo.location = (head[0] + 12, head[1] - 4, head[2] + 0.2)
    camo.rotation_euler = (math.pi/2, 0, math.pi/2 - math.atan2(4, 12))
    os.makedirs(icondir, exist_ok=True)
    for suffix, icon in (("", name), ("_b", name+"_blue"), ("_r", name+"_red")):
        tex.image = bpy.data.images.load(os.path.abspath(os.path.join(outdir, skins[suffix])))
        sc.render.filepath = os.path.abspath(os.path.join(icondir, icon+".jpg"))
        bpy.ops.render.render(write_still=True)

main()
