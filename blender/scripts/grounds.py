"""
Pocket Footy Manager — home grounds, one per division.

An aerial view of everything around the oval, rendered straight down so the
playing surface lines up exactly with the game's ground (the game draws the
turf and markings itself on top). 1 Blender unit = 100 ground units.

  4 Outback League   red dirt, picket fence, utes and cars around the boundary, gums, tin clubrooms
  3 Country League   grass banks, a small grandstand, cars, trees, scoreboard
  2 State League     stands down both wings, terraces behind the goals, four light towers
  1 National League  a full bowl, tiered stands, roof rim, light towers, big screens
  0 Worlds           an enclosed stadium under a clear perspex dome (variant via DOME env:
                     crystal = geodesic glass dome, retract = roof open over the ground with
                     glass panels parked at each end, pillow = glowing ETFE cushion ring)

Each division renders a colour image plus a seat mask (white where seating is
visible) so the game can paint the seats in the home club's colours.

  blender --background --python grounds.py -- <out_dir> [px_per_unit] [divisions e.g. 4321]
"""
import bpy, bmesh, math, os, sys, random
from mathutils import Vector, Euler

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
OUT = os.path.abspath(argv[0] if argv else 'grounds')
PX = float(argv[1]) if len(argv) > 1 else 1.4          # pixels per ground unit
DIVS = [int(c) for c in (argv[2] if len(argv) > 2 else '4321')]
DOME = os.environ.get('DOME', 'crystal')
os.makedirs(OUT, exist_ok=True)

# Ground frame (game viewBox): x -30..430, y -24..624  → Blender metres /100, centred
VB_X, VB_Y, VB_W, VB_H = -30, -24, 460, 648
RX, RY = 1.92, 2.88                                    # boundary ellipse
GL = (300 - 17.1) / 100                                # flat goal line

def new_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'; sc.cycles.samples = 48
    sc.cycles.use_denoising = False
    sc.render.resolution_x = int(VB_W * PX); sc.render.resolution_y = int(VB_H * PX)
    sc.render.image_settings.file_format = 'PNG'
    sc.view_settings.view_transform = 'Standard'
    # near-orthographic aerial camera: the ground plane maps exactly onto the viewBox,
    # tall things (towers, stands) lean outward a touch like a real aerial shot
    cd = bpy.data.cameras.new('Aerial'); cd.sensor_fit = 'VERTICAL'
    H = 14.0
    cd.angle = 2 * math.atan((VB_H / 200) / H)
    cd.clip_end = 100
    cam = bpy.data.objects.new('Aerial', cd); sc.collection.objects.link(cam)
    cx = (VB_X + VB_W / 2 - 200) / 100; cy = (300 - (VB_Y + VB_H / 2)) / 100
    cam.location = (cx, cy, H); sc.camera = cam
    sd = bpy.data.lights.new('Sun', 'SUN'); sd.energy = 3.4; sd.angle = math.radians(3)
    sun = bpy.data.objects.new('Sun', sd); sc.collection.objects.link(sun)
    sun.rotation_euler = Euler((math.radians(38), math.radians(-30), math.radians(-30)))  # light from top-left
    w = bpy.data.worlds.new('Sky'); sc.world = w; w.use_nodes = True
    w.node_tree.nodes['Background'].inputs['Color'].default_value = (0.62, 0.7, 0.8, 1)
    w.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.75
    return sc

def mat(name, rgb, rough=0.8, emit=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*rgb, 1); b.inputs['Roughness'].default_value = rough
    if emit:
        b.inputs['Emission Color'].default_value = (*rgb, 1); b.inputs['Emission Strength'].default_value = emit
    return m

def vcol_mat(name):
    """Material that takes per-face colour from the 'Col' attribute (crowd, cars)."""
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; b = nt.nodes['Principled BSDF']
    a = nt.nodes.new('ShaderNodeAttribute'); a.attribute_name = 'Col'
    nt.links.new(a.outputs['Color'], b.inputs['Base Color']); b.inputs['Roughness'].default_value = 0.85
    return m

def obj_from_bm(name, bm, materials, smooth=False):
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for m in materials: me.materials.append(m)
    if smooth:
        for p in me.polygons: p.use_smooth = True
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    return o

def boundary_pt(t, off=0.0):
    """Point on the boundary pushed outward by `off` (t = angle)."""
    x, y = (RX + off) * math.cos(t), (RY + off) * math.sin(t)
    return x, y

def box(bm, cx, cy, z0, sx, sy, sz, rot=0.0, color_layer=None, color=None, mat_index=0):
    r = bmesh.ops.create_cube(bm, size=1)
    vs = r['verts']
    bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=vs)
    bmesh.ops.rotate(bm, verts=vs, cent=(0, 0, 0), matrix=Euler((0, 0, rot)).to_matrix())
    bmesh.ops.translate(bm, verts=vs, vec=(cx, cy, z0 + sz / 2))
    faces = {f for v in vs for f in v.link_faces}
    for f in faces:
        f.material_index = mat_index
        if color_layer is not None:
            for l in f.loops: l[color_layer] = (*color, 1)
    return faces

def in_frame(x, y, pad=0.1):
    return (VB_X - 200) / 100 - pad < x < (VB_X + VB_W - 200) / 100 + pad and \
           (300 - VB_Y - VB_H) / 100 - pad < y < (300 - VB_Y) / 100 + pad

# ── building blocks ─────────────────────────────────────────────────────────
def ground_plane(rgb, rough=0.95, noise=0.0):
    bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=8)
    m = mat('Ground', rgb, rough)
    if noise:
        nt = m.node_tree; b = nt.nodes['Principled BSDF']
        n = nt.nodes.new('ShaderNodeTexNoise'); n.inputs['Scale'].default_value = 9; n.inputs['Detail'].default_value = 6
        mix = nt.nodes.new('ShaderNodeMix'); mix.data_type = 'RGBA'
        mix.inputs[6].default_value = (*[c * (1 - noise) for c in rgb], 1); mix.inputs[7].default_value = (*[min(1, c * (1 + noise)) for c in rgb], 1)
        nt.links.new(n.outputs['Fac'], mix.inputs[0]); nt.links.new(mix.outputs[2], b.inputs['Base Color'])
    return obj_from_bm('Ground', bm, [m])

def oval_turf():
    bm = bmesh.new(); bmesh.ops.create_circle(bm, cap_ends=True, segments=96, radius=1)
    bmesh.ops.scale(bm, vec=(RX + 0.03, RY + 0.03, 1), verts=bm.verts)
    bmesh.ops.translate(bm, verts=bm.verts, vec=(0, 0, 0.002))
    return obj_from_bm('Turf', bm, [mat('Turf', (0.12, 0.3, 0.07))])

def apron(width, rgb):
    """Strip just outside the boundary line (grass run-off or concrete)."""
    bm = bmesh.new(); n = 160
    outer = [bm.verts.new((*boundary_pt(2 * math.pi * i / n, width), 0.003)) for i in range(n)]
    inner = [bm.verts.new((*boundary_pt(2 * math.pi * i / n, -0.02), 0.003)) for i in range(n)]
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((inner[i], inner[j], outer[j], outer[i]))
    return obj_from_bm('Apron', bm, [mat('Apron', rgb)])

def fence(off, height, rgb, posts=False, boards=None):
    bm = bmesh.new(); n = 220
    if posts:   # picket fence: little posts
        for i in range(n):
            t = 2 * math.pi * i / n; x, y = boundary_pt(t, off)
            box(bm, x, y, 0, 0.018, 0.018, height, rot=t)
        for k in (0.4, 0.8):                # two rails
            for i in range(n):
                t0, t1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
                x0, y0 = boundary_pt(t0, off); x1, y1 = boundary_pt(t1, off)
                L = math.hypot(x1 - x0, y1 - y0); a = math.atan2(y1 - y0, x1 - x0)
                box(bm, (x0 + x1) / 2, (y0 + y1) / 2, height * k, L, 0.012, 0.012, rot=a)
        return obj_from_bm('Fence', bm, [mat('Pickets', rgb, 0.6)])
    cl = bm.loops.layers.color.new('Col')
    for i in range(n):
        t0, t1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        x0, y0 = boundary_pt(t0, off); x1, y1 = boundary_pt(t1, off)
        L = math.hypot(x1 - x0, y1 - y0); a = math.atan2(y1 - y0, x1 - x0)
        c = boards[(i // 6) % len(boards)] if boards else rgb
        box(bm, (x0 + x1) / 2, (y0 + y1) / 2, 0, L * 1.02, 0.03, height, rot=a, color_layer=cl, color=c)
    return obj_from_bm('Boards', bm, [vcol_mat('Boards')])

def stands(t0, t1, off0, depth, rows, rise, occupancy, rng, roof=0.0, roof_rgb=(0.86, 0.87, 0.88)):
    """Tiered seating around the boundary between angles t0..t1 (radians).
    Treads use the 'Seats' material (index 0, tinted in game), risers concrete (1)."""
    bm = bmesh.new(); segs = max(8, int(abs(t1 - t0) * 60))
    step = depth / rows
    crowd = []
    for r in range(rows):
        o0, o1 = off0 + r * step, off0 + (r + 1) * step
        z = (r + 1) * rise
        prev = None
        for s in range(segs + 1):
            t = t0 + (t1 - t0) * s / segs
            a0 = boundary_pt(t, o0); a1 = boundary_pt(t, o1)
            vin_lo = bm.verts.new((*a0, z - rise)); vin = bm.verts.new((*a0, z)); vout = bm.verts.new((*a1, z))
            if prev:
                f = bm.faces.new((prev[1], vin, vout, prev[2])); f.material_index = 0      # tread (seats)
                f2 = bm.faces.new((prev[0], vin_lo, vin, prev[1])); f2.material_index = 1  # riser
            prev = (vin_lo, vin, vout)
            # spectators on this tread
            if s < segs:
                tm = t0 + (t1 - t0) * (s + 0.5) / segs
                arc = math.hypot(*[a - b for a, b in zip(boundary_pt(t0 + (t1 - t0) * (s + 1) / segs, o0), boundary_pt(t, o0))])
                for k in range(max(1, int(arc / 0.042))):
                    if rng.random() < occupancy:
                        tt = t + (t1 - t0) / segs * (k + 0.5) / max(1, int(arc / 0.042))
                        px, py = boundary_pt(tt, (o0 + o1) / 2 + rng.uniform(-0.01, 0.01))
                        if in_frame(px, py): crowd.append((px, py, z))
        # back wall at the top of the stand
    o = obj_from_bm('Stand', bm, [SEATS, CONCRETE])
    if roof:
        rb = bmesh.new()
        prev = None
        for s in range(segs + 1):
            t = t0 + (t1 - t0) * s / segs
            ai = boundary_pt(t, off0 + depth * (1 - roof)); ao = boundary_pt(t, off0 + depth + 0.05)
            zr = rows * rise + 0.12
            v1 = rb.verts.new((*ai, zr)); v2 = rb.verts.new((*ao, zr + 0.04))
            if prev: rb.faces.new((prev[0], v1, v2, prev[1]))
            prev = (v1, v2)
        obj_from_bm('Roof', rb, [mat('Roof', roof_rgb, 0.4)])
    return crowd

def add_crowd(points, rng, palette):
    bm = bmesh.new(); cl = bm.loops.layers.color.new('Col')
    for (x, y, z) in points:
        c = palette[rng.randrange(len(palette))]
        c = tuple(min(1, max(0, v * rng.uniform(0.8, 1.15))) for v in c)
        box(bm, x, y, z, 0.026, 0.026, 0.03, rot=rng.uniform(0, 3), color_layer=cl, color=c)
        # head
        box(bm, x, y, z + 0.03, 0.016, 0.016, 0.014, color_layer=cl, color=(0.75, 0.55, 0.42))
    return obj_from_bm('Crowd', bm, [vcol_mat('Crowd')])

def cars_ring(rng, off0, off1, count, t_ranges, colours):
    bm = bmesh.new(); cl = bm.loops.layers.color.new('Col')
    glass = (0.08, 0.1, 0.12)
    placed = 0; tries = 0
    pts = []
    while placed < count and tries < count * 40:
        tries += 1
        lo, hi = rng.choice(t_ranges); t = rng.uniform(lo, hi)
        off = rng.choice([off0, off0 + 0.26, off0 + 0.52]) if off1 > off0 + 0.4 else off0
        if off > off1: continue
        x, y = boundary_pt(t, off + 0.1)
        if not in_frame(x, y, -0.05): continue
        if any(math.hypot(x - a, y - b) < 0.13 for a, b in pts): continue
        pts.append((x, y))
        # parked nose-in toward the ground
        nx, ny = math.cos(t) * RY, math.sin(t) * RX
        ang = math.atan2(ny, nx) + math.pi / 2
        c = rng.choice(colours)
        is_ute = rng.random() < 0.35
        L, Wd = 0.2, 0.09
        box(bm, x, y, 0, Wd, L, 0.045, rot=ang - math.pi / 2 + math.pi / 2, color_layer=cl, color=c)
        # cabin: toward the ground end for utes (tray behind), centred for sedans
        cab_off = 0.03 if is_ute else 0.0
        cxo = x - math.cos(t) * cab_off; cyo = y - math.sin(t) * cab_off
        box(bm, cxo, cyo, 0.045, Wd * 0.86, L * (0.38 if is_ute else 0.5), 0.035, rot=ang, color_layer=cl, color=glass)
        placed += 1
    return obj_from_bm('Cars', bm, [vcol_mat('Cars')])

def gum_tree(bm, cl, x, y, rng, size=1.0):
    for k in range(5):
        ox, oy = rng.uniform(-0.07, 0.07) * size, rng.uniform(-0.07, 0.07) * size
        r = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=rng.uniform(0.06, 0.1) * size)
        bmesh.ops.translate(bm, verts=r['verts'], vec=(x + ox, y + oy, 0.12 * size + rng.uniform(0, 0.05)))
        g = rng.choice([(0.24, 0.32, 0.16), (0.3, 0.38, 0.2), (0.2, 0.28, 0.14)])
        for v in r['verts']:
            for f in v.link_faces:
                for l in f.loops: l[cl] = (*g, 1)

def trees(rng, n, t_ranges, off0, off1, size=1.0):
    bm = bmesh.new(); cl = bm.loops.layers.color.new('Col')
    done = 0; tries = 0
    while done < n and tries < n * 30:
        tries += 1
        lo, hi = rng.choice(t_ranges); t = rng.uniform(lo, hi)
        x, y = boundary_pt(t, rng.uniform(off0, off1))
        if not in_frame(x, y, 0.05): continue
        gum_tree(bm, cl, x, y, rng, size * rng.uniform(0.8, 1.2)); done += 1
    return obj_from_bm('Trees', bm, [vcol_mat('Trees')], smooth=False)

def light_tower(x, y, h=1.25):
    bm = bmesh.new()
    box(bm, x, y, 0, 0.03, 0.03, h)
    t = math.atan2(-y, -x)
    box(bm, x, y, h, 0.2, 0.07, 0.05, rot=t + math.pi / 2, mat_index=1)
    return obj_from_bm('Tower', bm, [mat('Steel', (0.55, 0.56, 0.58), 0.5), mat('Lamps', (1, 0.97, 0.85), 0.3, emit=2.5)])

def building(x, y, w, d, h, rot, wall, roof_rgb, gable=True):
    bm = bmesh.new()
    box(bm, x, y, 0, w, d, h, rot=rot)
    if gable:
        # pitched roof — two sloped faces
        r = Euler((0, 0, rot)).to_matrix()
        def P(a, b, c): return Vector((x, y, 0)) + r @ Vector((a, b, c))
        hw, hd = w / 2 + 0.01, d / 2 + 0.01
        v = [bm.verts.new(P(-hw, -hd, h)), bm.verts.new(P(hw, -hd, h)), bm.verts.new(P(hw, 0, h + 0.05)), bm.verts.new(P(-hw, 0, h + 0.05)),
             bm.verts.new(P(-hw, hd, h)), bm.verts.new(P(hw, hd, h))]
        f1 = bm.faces.new((v[0], v[1], v[2], v[3])); f1.material_index = 1
        f2 = bm.faces.new((v[3], v[2], v[5], v[4])); f2.material_index = 1
    else:
        f = box(bm, x, y, h, w + 0.02, d + 0.02, 0.012, rot=rot, mat_index=1)
    return obj_from_bm('Building', bm, [mat('Wall', wall), mat('RoofTin', roof_rgb, 0.45)])


# ── props: everything that gives a ground its character ─────────────────────
class Props:
    """One vertex-coloured mesh that small scenery is added to."""
    def __init__(self):
        self.bm = bmesh.new(); self.cl = self.bm.loops.layers.color.new('Col')
    def _paint(self, verts, color):
        for f in {f for v in verts for f in v.link_faces}:
            for l in f.loops: l[self.cl] = (*color, 1)
    def box(self, x, y, z0, sx, sy, sz, color, rot=0.0):
        box(self.bm, x, y, z0, sx, sy, sz, rot=rot, color_layer=self.cl, color=color)
    def flat(self, x, y, sx, sy, color, rot=0.0, z=0.004):
        self.box(x, y, z, sx, sy, 0.003, color, rot)
    def cyl(self, x, y, z0, r, h, color, segs=18, r_top=None):
        res = bmesh.ops.create_cone(self.bm, cap_ends=True, segments=segs, radius1=r, radius2=r if r_top is None else r_top, depth=h)
        bmesh.ops.translate(self.bm, verts=res['verts'], vec=(x, y, z0 + h / 2)); self._paint(res['verts'], color)
    def wheel(self, x, y, z, r, color, yaw=0.0, thick=0.012):
        """A disc standing on edge (windmill rotor, clock face) — mostly seen by its shadow."""
        res = bmesh.ops.create_cone(self.bm, cap_ends=True, segments=20, radius1=r, radius2=r, depth=thick)
        bmesh.ops.rotate(self.bm, verts=res['verts'], cent=(0, 0, 0), matrix=Euler((math.radians(90), 0, yaw)).to_matrix())
        bmesh.ops.translate(self.bm, verts=res['verts'], vec=(x, y, z)); self._paint(res['verts'], color)
    def blob(self, x, y, z, r, color, squash=1.0):
        res = bmesh.ops.create_icosphere(self.bm, subdivisions=1, radius=r)
        bmesh.ops.scale(self.bm, vec=(1, 1, squash), verts=res['verts'])
        bmesh.ops.translate(self.bm, verts=res['verts'], vec=(x, y, z)); self._paint(res['verts'], color)
    def gable(self, x, y, w, d, h, rot, wall, roof, ridge=0.07, verandah=None):
        """Shed / house: walls, a pitched roof, optionally a verandah strip on the -d side."""
        self.box(x, y, 0, w, d, h, wall, rot)
        r = Euler((0, 0, rot)).to_matrix()
        def P(a, b, c): return Vector((x, y, 0)) + r @ Vector((a, b, c))
        hw, hd = w / 2 + 0.012, d / 2 + 0.012
        v = [self.bm.verts.new(P(*p)) for p in ((-hw, -hd, h), (hw, -hd, h), (hw, 0, h + ridge), (-hw, 0, h + ridge), (-hw, hd, h), (hw, hd, h))]
        f1 = self.bm.faces.new((v[0], v[1], v[2], v[3])); f2 = self.bm.faces.new((v[3], v[2], v[5], v[4]))
        dark = tuple(c * 0.82 for c in roof)
        for l in f1.loops: l[self.cl] = (*roof, 1)
        for l in f2.loops: l[self.cl] = (*dark, 1)
        if verandah:
            p = P(0, -hd - 0.035, 0)
            self.box(p.x, p.y, h * 0.7, w, 0.07, 0.008, verandah, rot)
    def done(self, name='Props'):
        return obj_from_bm(name, self.bm, [vcol_mat(name)])

def scatter(rng, n, off0, off1, t_ranges=None, pad=0.0):
    """Random points around the ground, inside the picture."""
    out = []; tries = 0
    while len(out) < n and tries < n * 40:
        tries += 1
        lo, hi = rng.choice(t_ranges) if t_ranges else (0, 2 * math.pi)
        x, y = boundary_pt(rng.uniform(lo, hi), rng.uniform(off0, off1))
        if in_frame(x, y, pad): out.append((x, y))
    return out

def road(p, t0, t1, off, width, color, line=None, steps=40):
    """A road following the ground's curve; `line` adds a dashed centre line."""
    for i in range(steps):
        ta, tb = t0 + (t1 - t0) * i / steps, t0 + (t1 - t0) * (i + 1) / steps
        xa, ya = boundary_pt(ta, off); xb, yb = boundary_pt(tb, off)
        L = math.hypot(xb - xa, yb - ya); a = math.atan2(yb - ya, xb - xa)
        p.flat((xa + xb) / 2, (ya + yb) / 2, L * 1.05, width, color, a, z=0.003)
        if line and i % 2 == 0: p.flat((xa + xb) / 2, (ya + yb) / 2, L * 0.55, 0.012, line, a, z=0.006)

def hill(t0, t1, off0, depth, height, rgb):
    """A grassed bank behind the fence (people sit on it instead of in seats)."""
    bm = bmesh.new(); segs = max(8, int(abs(t1 - t0) * 50)); prev = None
    for s in range(segs + 1):
        t = t0 + (t1 - t0) * s / segs
        a = bm.verts.new((*boundary_pt(t, off0), 0.004)); b = bm.verts.new((*boundary_pt(t, off0 + depth * 0.7), height)); c = bm.verts.new((*boundary_pt(t, off0 + depth), height))
        if prev: bm.faces.new((prev[0], a, b, prev[1])); bm.faces.new((prev[1], b, c, prev[2]))
        prev = (a, b, c)
    return obj_from_bm('Hill', bm, [mat('HillGrass', rgb, 0.95)])

def flagpoles(p, pts, colours, h=0.5):
    for i, (x, y) in enumerate(pts):
        p.box(x, y, 0, 0.012, 0.012, h, (0.9, 0.9, 0.9))
        p.box(x + 0.045, y, h - 0.07, 0.09, 0.006, 0.06, colours[i % len(colours)])

# ── Worlds: perspex dome ────────────────────────────────────────────────────
def perspex(name, tint=(0.86, 0.94, 1.0), gloss=0.22, rough=0.04):
    """Thin clear sheet: mostly see-through, with glossy reflections at glancing angles."""
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    tr = nt.nodes.new('ShaderNodeBsdfTransparent'); tr.inputs['Color'].default_value = (*tint, 1)
    gl = nt.nodes.new('ShaderNodeBsdfGlossy'); gl.inputs['Roughness'].default_value = rough
    gl.inputs['Color'].default_value = (0.92, 0.97, 1, 1)
    fr = nt.nodes.new('ShaderNodeLayerWeight'); fr.inputs['Blend'].default_value = gloss
    mx = nt.nodes.new('ShaderNodeMixShader')
    nt.links.new(fr.outputs['Fresnel'], mx.inputs[0]); nt.links.new(tr.outputs[0], mx.inputs[1]); nt.links.new(gl.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out.inputs['Surface'])
    m.blend_method = 'BLEND' if hasattr(m, 'blend_method') else None
    return m

def dome_pt(t, u, ax, ay, h, z0):
    """Point on a half-ellipsoid dome: t = angle around, u = 0 (rim) .. 1 (crown)."""
    ph = u * math.pi / 2
    return (ax * math.cos(ph) * math.cos(t), ay * math.cos(ph) * math.sin(t), z0 + h * math.sin(ph))

def rib(bm, p0, p1, w):
    x0, y0, z0 = p0; x1, y1, z1 = p1
    L = math.dist(p0, p1); a = math.atan2(y1 - y0, x1 - x0)
    r = bmesh.ops.create_cube(bm, size=1); vs = r['verts']
    bmesh.ops.scale(bm, vec=(L, w, w), verts=vs)
    pitch = math.atan2(z1 - z0, math.hypot(x1 - x0, y1 - y0))
    bmesh.ops.rotate(bm, verts=vs, cent=(0, 0, 0), matrix=Euler((0, -pitch, a), 'XYZ').to_matrix())
    bmesh.ops.translate(bm, verts=vs, vec=((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))

def glass_dome(ax, ay, h, z0, n_mer=28, n_ring=6, rib_w=0.022, sheet=True, open_u=None, tint=(0.86, 0.94, 1.0)):
    """Clear sheet + white steel lattice. open_u: leave the crown open above this u."""
    top = open_u if open_u else 1.0
    if sheet:
        bm = bmesh.new(); NT, NU = 120, 26
        rows = []
        for j in range(NU + 1):
            u = top * j / NU
            rows.append([bm.verts.new(dome_pt(2 * math.pi * i / NT, u, ax, ay, h, z0)) for i in range(NT)])
        for j in range(NU):
            for i in range(NT):
                k = (i + 1) % NT
                bm.faces.new((rows[j][i], rows[j][k], rows[j + 1][k], rows[j + 1][i]))
        if not open_u:
            c = bm.verts.new(dome_pt(0, 1, ax, ay, h, z0))
        o = obj_from_bm('DomeSheet', bm, [perspex('Perspex', tint)], smooth=True)
        DOME_OBJS.append(o)
    bm = bmesh.new()
    # Lamella lattice: two families of spiral ribs crossing in diamonds (no starburst at the crown),
    # a stiff crown ring, and a few horizontal rings
    crown = top if open_u else 0.9
    N = 22
    for i in range(n_mer):
        for sgn in (1, -1):
            t0 = 2 * math.pi * i / n_mer
            for j in range(N):
                u0, u1 = crown * j / N, crown * (j + 1) / N
                rib(bm, dome_pt(t0 + sgn * 1.15 * u0, u0, ax, ay, h, z0), dome_pt(t0 + sgn * 1.15 * u1, u1, ax, ay, h, z0), rib_w * 0.75)
    for r in range(1, n_ring + 1):
        u = crown * r / n_ring; M = 120
        w = rib_w * (2.6 if r == n_ring else 0.6)
        for i in range(M):
            rib(bm, dome_pt(2 * math.pi * i / M, u, ax, ay, h, z0), dome_pt(2 * math.pi * (i + 1) / M, u, ax, ay, h, z0), w)
    if not open_u:   # glazed cap inside the crown ring, a few straight spokes
        for i in range(8):
            t = 2 * math.pi * i / 8
            rib(bm, dome_pt(t, crown, ax, ay, h, z0), dome_pt(t, 1.0, ax, ay, h, z0), rib_w * 0.5)
    o = obj_from_bm('DomeRibs', bm, [mat('DomeSteel', (0.93, 0.94, 0.96), 0.3)])
    DOME_OBJS.append(o)

def ring_roof(off_in, off_out, z, rgb, name='RingRoof', segs=160):
    bm = bmesh.new(); prev = None
    for s in range(segs + 1):
        t = 2 * math.pi * s / segs
        v1 = bm.verts.new((*boundary_pt(t, off_in), z)); v2 = bm.verts.new((*boundary_pt(t, off_out), z + 0.05))
        if prev: bm.faces.new((prev[0], v1, v2, prev[1]))
        prev = (v1, v2)
    return obj_from_bm(name, bm, [mat(name, rgb, 0.35)])

def led_ring(off, z, rgb, strength=4.0, w=0.03):
    bm = bmesh.new(); prev = None; segs = 200
    for s in range(segs + 1):
        t = 2 * math.pi * s / segs
        v1 = bm.verts.new((*boundary_pt(t, off), z)); v2 = bm.verts.new((*boundary_pt(t, off + w), z))
        if prev: bm.faces.new((prev[0], v1, v2, prev[1]))
        prev = (v1, v2)
    return obj_from_bm('LED', bm, [mat('LED', rgb, 0.3, emit=strength)])

def pillow_ring(off0, off1, z0, rgb, rng, rows=3, per=64):
    """ETFE cushions: puffy diamond panels in a ring, softly lit from inside."""
    bm = bmesh.new()
    for r in range(rows):
        o0 = off0 + (off1 - off0) * r / rows; o1 = off0 + (off1 - off0) * (r + 1) / rows
        for i in range(per):
            t0 = 2 * math.pi * (i + 0.5 * (r % 2)) / per; t1 = t0 + 2 * math.pi / per
            tm = (t0 + t1) / 2; om = (o0 + o1) / 2
            zr = z0 + 0.12 * r
            a = bm.verts.new((*boundary_pt(tm, o0), zr)); b = bm.verts.new((*boundary_pt(t1, om), zr + 0.06))
            c = bm.verts.new((*boundary_pt(tm, o1), zr + 0.12)); d = bm.verts.new((*boundary_pt(t0, om), zr + 0.06))
            m = bm.verts.new((*boundary_pt(tm, om), zr + 0.1))   # puffed centre
            for e in ((a, b, m), (b, c, m), (c, d, m), (d, a, m)): bm.faces.new(e)
    m = bpy.data.materials.new('ETFE'); m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*rgb, 1); b.inputs['Roughness'].default_value = 0.15
    b.inputs['Emission Color'].default_value = (*rgb, 1); b.inputs['Emission Strength'].default_value = 0.9
    b.inputs['Coat Weight'].default_value = 1.0
    o = obj_from_bm('Pillows', bm, [m], smooth=False)
    return o

# ── divisions ───────────────────────────────────────────────────────────────
def build(div):
    global SEATS, CONCRETE, DOME_OBJS
    DOME_OBJS = []
    sc = new_scene(); rng = random.Random(100 + div)
    SEATS = mat('Seats', (0.78, 0.78, 0.8), 0.6)
    CONCRETE = mat('Concrete', (0.58, 0.57, 0.55))
    oval_turf()
    TAU = math.pi * 2
    car_cols = [(0.9, 0.9, 0.9), (0.75, 0.1, 0.08), (0.1, 0.2, 0.5), (0.15, 0.15, 0.16), (0.6, 0.62, 0.65), (0.85, 0.75, 0.55), (0.2, 0.35, 0.2), (0.95, 0.85, 0.2)]
    crowd_pal = [(0.85, 0.85, 0.85), (0.15, 0.15, 0.18), (0.6, 0.12, 0.1), (0.12, 0.22, 0.5), (0.9, 0.75, 0.2), (0.3, 0.5, 0.25), (0.55, 0.45, 0.35), (0.8, 0.5, 0.6)]
    corners = [(math.radians(a - 28), math.radians(a + 28)) for a in (45, 135, 225, 315)]
    wings = [(math.radians(-25), math.radians(25)), (math.radians(155), math.radians(205))]
    pockets = [(math.radians(60), math.radians(120)), (math.radians(240), math.radians(300))]
    p = Props()
    if div == 4:
        # ── OUTBACK: red dirt, utes round the fence, a tin shed, a windmill and a mob of sheep ──
        ground_plane((0.55, 0.3, 0.16), noise=0.25)                        # red dirt
        apron(0.06, (0.42, 0.42, 0.2))                                     # dry grass run-off
        fence(0.07, 0.05, (0.95, 0.95, 0.92), posts=True)
        road(p, math.radians(-30), math.radians(34), 0.66, 0.2, (0.66, 0.43, 0.27))            # the track in from the highway
        road(p, math.radians(-30), math.radians(34), 0.61, 0.02, (0.5, 0.3, 0.18)); road(p, math.radians(-30), math.radians(34), 0.71, 0.02, (0.5, 0.3, 0.18))   # wheel ruts
        cars_ring(rng, 0.1, 0.36, 60, [(0, TAU)], car_cols)
        trees(rng, 16, [corners[1], corners[3]], 0.75, 1.6, 1.3)
        # clubrooms: a tin shed with a rusty roof and a verandah, rainwater tank beside it
        p.gable(-1.72, 2.62, 0.5, 0.26, 0.09, math.radians(-40), (0.8, 0.78, 0.7), (0.56, 0.3, 0.17), verandah=(0.72, 0.72, 0.7))
        p.cyl(-2.02, 2.36, 0, 0.085, 0.14, (0.74, 0.76, 0.78)); p.cyl(-2.02, 2.36, 0.14, 0.085, 0.02, (0.6, 0.62, 0.64), r_top=0.02)
        p.gable(1.85, -2.62, 0.22, 0.16, 0.07, math.radians(40), (0.7, 0.68, 0.6), (0.62, 0.64, 0.66))     # canteen
        for k in range(3): p.cyl(1.62 + k * 0.07, -2.86, 0, 0.022, 0.05, (0.2, 0.3, 0.55) if k % 2 else (0.7, 0.15, 0.1))   # 44-gallon drum bins
        # the old scoreboard on its scaffold
        p.box(1.95, 2.55, 0.12, 0.34, 0.05, 0.2, (0.1, 0.1, 0.1), math.radians(-35)); p.box(1.95, 2.55, 0, 0.3, 0.03, 0.12, (0.45, 0.33, 0.2), math.radians(-35))
        # windmill and stock trough: the wheel throws its shadow across the dirt
        wx, wy = -1.72, -2.78
        for dx, dy in ((-0.04, -0.04), (0.04, -0.04), (0.04, 0.04), (-0.04, 0.04)): p.box(wx + dx * 1.4, wy + dy * 1.4, 0, 0.016, 0.016, 0.75, (0.6, 0.6, 0.62))
        p.wheel(wx, wy - 0.06, 0.8, 0.23, (0.72, 0.74, 0.76), yaw=math.radians(30)); p.box(wx + 0.08, wy + 0.1, 0.79, 0.22, 0.008, 0.08, (0.7, 0.2, 0.15), math.radians(120))
        p.cyl(wx - 0.32, wy + 0.3, 0.002, 0.3, 0.004, (0.42, 0.3, 0.2), segs=24); p.cyl(wx - 0.32, wy + 0.3, 0.004, 0.24, 0.004, (0.3, 0.42, 0.45), segs=24)   # the dam
        p.cyl(wx + 0.26, wy - 0.12, 0, 0.1, 0.035, (0.5, 0.5, 0.5)); p.cyl(wx + 0.26, wy - 0.12, 0.03, 0.085, 0.008, (0.2, 0.42, 0.55))
        # a mob of sheep in the paddock behind the scoreboard end, wire fence round them
        for (x, y) in scatter(rng, 22, 0.78, 1.2, [(math.radians(40), math.radians(60))]):
            p.blob(x, y, 0.035, 0.045, (0.95, 0.94, 0.9), 0.7); p.blob(x + 0.04, y + 0.012, 0.04, 0.018, (0.2, 0.18, 0.16))
        for i in range(14):
            x, y = boundary_pt(math.radians(37 + i * 2), 0.72); p.box(x, y, 0, 0.014, 0.014, 0.07, (0.5, 0.42, 0.32))
        # spinifex, rocks and a few locals on camp chairs by their utes
        for (x, y) in scatter(rng, 150, 0.7, 1.7): p.blob(x, y, 0.012, rng.uniform(0.02, 0.04), rng.choice([(0.62, 0.58, 0.3), (0.5, 0.5, 0.26), (0.7, 0.62, 0.36)]), 0.5)
        for (x, y) in scatter(rng, 26, 0.75, 1.7): p.blob(x, y, 0.01, rng.uniform(0.02, 0.045), (0.48, 0.3, 0.22), 0.6)
        add_crowd([(x, y, 0) for (x, y) in scatter(rng, 70, 0.1, 0.26)], rng, crowd_pal)
    elif div == 3:
        # ── COUNTRY: the footy-netball club — timber grandstand, netball court, pine windbreak ──
        ground_plane((0.22, 0.36, 0.14), noise=0.18)                       # grass surrounds
        apron(0.06, (0.2, 0.38, 0.12))
        fence(0.07, 0.05, (0.95, 0.95, 0.92), posts=True)
        crowd = stands(math.radians(160), math.radians(200), 0.12, 0.42, 6, 0.04, 0.55, rng, roof=0.6, roof_rgb=(0.16, 0.34, 0.22))   # old grandstand, green tin roof
        bank = []
        for _ in range(900):
            t = rng.uniform(0, TAU)
            if math.radians(155) < t < math.radians(205): continue
            x, y = boundary_pt(t, rng.uniform(0.1, 0.24))
            if in_frame(x, y): bank.append((x, y, 0))
        add_crowd(crowd + bank, rng, crowd_pal)
        # gravel car parks in the two right-hand corners, cars parked on them
        for a in (38, -38):
            x, y = boundary_pt(math.radians(a), 0.75); p.flat(x, y, 1.0, 0.85, (0.56, 0.54, 0.48), math.radians(a) + math.pi / 2, z=0.002)
        cars_ring(rng, 0.32, 0.9, 50, [corners[0], corners[3]], car_cols)
        # netball court (top-left): blue court, white lines, a ring at each end
        nx, ny, nr = -1.72, 2.72, math.radians(38)
        R = Euler((0, 0, nr)).to_matrix()
        def N(a, b): v = R @ Vector((a, b, 0)); return nx + v.x, ny + v.y
        p.flat(nx, ny, 0.74, 0.42, (0.2, 0.42, 0.24), nr, z=0.003); p.flat(nx, ny, 0.66, 0.34, (0.18, 0.42, 0.62), nr, z=0.005)
        for a in (-0.33, -0.11, 0.11, 0.33): x, y = N(a, 0); p.flat(x, y, 0.008, 0.34, (0.95, 0.95, 0.95), nr, z=0.007)
        for b in (-0.17, 0.17): x, y = N(0, b); p.flat(x, y, 0.66, 0.008, (0.95, 0.95, 0.95), nr, z=0.007)
        for a in (-0.33, 0.33): x, y = N(a, 0); p.box(x, y, 0, 0.012, 0.012, 0.16, (0.9, 0.9, 0.9)); p.cyl(x, y, 0.16, 0.03, 0.006, (0.9, 0.35, 0.1))
        add_crowd([(*N(rng.uniform(-0.3, 0.3), rng.uniform(-0.15, 0.15)), 0) for _ in range(12)], rng, [(0.85, 0.2, 0.3), (0.2, 0.3, 0.75)])
        # clubrooms (top-right): weatherboard, red tin roof, verandah, tank; canteen caravan with a striped awning
        p.gable(1.9, 2.72, 0.5, 0.24, 0.09, math.radians(-38), (0.88, 0.86, 0.8), (0.6, 0.16, 0.12), verandah=(0.75, 0.75, 0.72))
        p.cyl(2.16, 2.42, 0, 0.07, 0.12, (0.3, 0.45, 0.32))
        p.box(1.52, 2.95, 0, 0.2, 0.09, 0.07, (0.95, 0.95, 0.93), math.radians(-38)); p.box(1.49, 2.9, 0.07, 0.2, 0.06, 0.006, (0.85, 0.2, 0.15), math.radians(-38))
        # scoreboard hut (bottom-left) and the curator's roller
        p.gable(-1.95, -2.6, 0.4, 0.1, 0.2, math.radians(-35), (0.1, 0.1, 0.1), (0.75, 0.75, 0.72), ridge=0.03)
        p.box(-1.55, -2.92, 0, 0.1, 0.07, 0.05, (0.18, 0.45, 0.2), 0.4); p.cyl(-1.62, -2.95, 0.01, 0.03, 0.08, (0.4, 0.4, 0.42))
        # cricket nets (bottom-right): two synthetic pitches inside a wire cage
        cx, cy, cr = 1.9, -2.78, math.radians(35)
        Rc = Euler((0, 0, cr)).to_matrix()
        for k in (-0.06, 0.06):
            v = Rc @ Vector((0, k, 0)); p.flat(cx + v.x, cy + v.y, 0.5, 0.09, (0.3, 0.52, 0.3), cr, z=0.004)
        for k in (-0.12, 0, 0.12):
            v = Rc @ Vector((0, k, 0)); p.box(cx + v.x, cy + v.y, 0, 0.5, 0.006, 0.09, (0.6, 0.62, 0.62), cr)
        # playground by the clubrooms, a pine windbreak down the left boundary, gums elsewhere
        for (dx, dy, c, sx, sy, h) in ((0, 0, (0.95, 0.8, 0.15), 0.12, 0.03, 0.06), (0.1, 0.08, (0.85, 0.2, 0.15), 0.03, 0.12, 0.09), (-0.08, 0.1, (0.2, 0.45, 0.8), 0.06, 0.06, 0.04)):
            p.box(1.35 + dx, 3.08 + dy, 0, sx, sy, h, c, 0.5)
        p.cyl(1.2, 3.12, 0, 0.07, 0.008, (0.85, 0.78, 0.6))
        for i in range(11):
            x, y = boundary_pt(math.radians(207 + i * 3.1), 0.42 + 0.02 * (i % 2))
            if in_frame(x, y): p.cyl(x, y, 0, 0.075, 0.3, (0.1, 0.24, 0.14) if i % 2 else (0.12, 0.28, 0.16), segs=8, r_top=0.005)
        trees(rng, 14, [corners[1], corners[2]], 1.0, 1.7, 1.2)
    elif div == 2:
        # ── STATE: a suburban league ground — heritage grandstand, the hill, a tram going past ──
        ground_plane((0.5, 0.5, 0.48), noise=0.08)                          # concrete concourse
        apron(0.08, (0.14, 0.33, 0.09))
        fence(0.09, 0.035, None, boards=[(0.08, 0.15, 0.4), (0.95, 0.95, 0.95), (0.7, 0.1, 0.1), (0.1, 0.1, 0.1)])
        crowd = []
        crowd += stands(math.radians(-38), math.radians(38), 0.12, 1.3, 14, 0.035, 0.62, rng, roof=0.35)                              # modern stand
        crowd += stands(math.radians(142), math.radians(218), 0.12, 0.6, 7, 0.04, 0.7, rng, roof=0.72, roof_rgb=(0.55, 0.22, 0.15))    # heritage stand, terracotta roof
        crowd += stands(math.radians(52), math.radians(128), 0.12, 0.9, 9, 0.025, 0.45, rng)     # terrace behind the top goals
        # the hill behind the bottom goals: people on rugs
        hill(math.radians(232), math.radians(308), 0.12, 0.9, 0.16, (0.2, 0.4, 0.13))
        hillp = [(x, y, 0.1) for (x, y) in scatter(rng, 420, 0.16, 0.9, [(math.radians(233), math.radians(307))])]
        for (x, y, z) in hillp[::9]: p.flat(x, y, 0.07, 0.05, rng.choice([(0.8, 0.2, 0.2), (0.2, 0.35, 0.7), (0.9, 0.8, 0.3), (0.85, 0.85, 0.85)]), rng.uniform(0, 3), z=0.13)
        add_crowd(crowd + hillp, rng, crowd_pal)
        for a in (40, 140, 220, 320):
            x, y = boundary_pt(math.radians(a), 0.72); light_tower(x, y)
        # heritage stand: clock turret on the roof ridge and a row of flags
        for ang in (152, 208):
            tx, ty = boundary_pt(math.radians(ang), 0.52)
            p.box(tx, ty, 0.4, 0.16, 0.16, 0.22, (0.92, 0.89, 0.8)); p.cyl(tx, ty, 0.62, 0.13, 0.14, (0.4, 0.16, 0.12), segs=4, r_top=0.005)
            p.cyl(tx, ty, 0.615, 0.05, 0.004, (0.97, 0.97, 0.95))
        flagpoles(p, [boundary_pt(math.radians(a), 0.3) for a in (146, 160, 172, 188, 200, 214)], [(0.8, 0.1, 0.1), (0.1, 0.2, 0.6), (0.95, 0.85, 0.2), (0.95, 0.95, 0.95)], h=0.75)
        # solar panels on the modern stand's roof
        for a in range(-30, 31, 10):
            x, y = boundary_pt(math.radians(a), 1.15); p.flat(x, y, 0.16, 0.2, (0.08, 0.12, 0.3), math.radians(a), z=0.66)
        # electronic scoreboard above the terrace
        x, y = boundary_pt(math.radians(90), 0.95)
        sb = bmesh.new(); box(sb, x, y, 0.3, 0.6, 0.06, 0.3); obj_from_bm('Screen', sb, [mat('Screen', (0.12, 0.2, 0.32), 0.3, emit=1.0)])
        # the street outside two corners: bitumen, a centre line, terrace-house roofs, plane trees, a tram
        for (a0, a1) in ((38, 52), (218, 232)):
            road(p, math.radians(a0 - 4), math.radians(a1 + 4), 1.08, 0.2, (0.19, 0.19, 0.21), line=(0.9, 0.9, 0.85), steps=16)
        roofs = [(0.55, 0.25, 0.18), (0.35, 0.36, 0.38), (0.25, 0.25, 0.27), (0.62, 0.3, 0.2), (0.5, 0.5, 0.48)]
        for i in range(7):
            x, y = boundary_pt(math.radians(36 + i * 3), 1.3)
            if in_frame(x, y, 0.1): p.gable(x, y, 0.12, 0.2, 0.1, math.radians(36 + i * 3) + math.pi / 2, (0.8, 0.76, 0.7), roofs[i % 5], ridge=0.05)
        x, y = boundary_pt(math.radians(226), 1.08)                         # the tram: green and cream
        p.box(x, y, 0.01, 0.34, 0.08, 0.09, (0.12, 0.36, 0.2), math.radians(226) + math.pi / 2); p.box(x, y, 0.1, 0.33, 0.07, 0.012, (0.92, 0.88, 0.72), math.radians(226) + math.pi / 2)
        trees(rng, 8, [(math.radians(40), math.radians(50)), (math.radians(310), math.radians(322)), (math.radians(128), math.radians(142))], 0.85, 1.0, 0.9)
    else:
        # ── NATIONAL: the big-league stadium — two tiers, a roof canopy with its trusses, corporate glass, LED ribbon ──
        ground_plane((0.45, 0.45, 0.44), noise=0.05)
        apron(0.08, (0.13, 0.32, 0.08))
        fence(0.09, 0.035, None, boards=[(0.05, 0.05, 0.08), (0.95, 0.75, 0.1), (0.95, 0.95, 0.95), (0.1, 0.3, 0.75)])
        crowd = stands(0, TAU, 0.12, 0.72, 10, 0.04, 0.88, rng)                    # lower tier
        crowd += stands(0, TAU, 0.98, 0.75, 9, 0.055, 0.82, rng, roof=0.85)          # upper tier under the canopy
        add_crowd(crowd, rng, crowd_pal)
        # corporate boxes: a band of dark glass between the tiers, lit from inside
        gb = bmesh.new(); prev = None
        for s_ in range(201):
            t = TAU * s_ / 200
            v1 = gb.verts.new((*boundary_pt(t, 0.84), 0.42)); v2 = gb.verts.new((*boundary_pt(t, 0.98), 0.46))
            if prev: gb.faces.new((prev[0], v1, v2, prev[1]))
            prev = (v1, v2)
        obj_from_bm('Boxes', gb, [mat('BoxGlass', (0.12, 0.2, 0.3), 0.1, emit=0.5)])
        led_ring(0.105, 0.04, (1.0, 0.85, 0.3), 3.0, 0.012)                         # LED ribbon round the fence
        led_ring(0.86, 0.47, (1.0, 0.95, 0.8), 2.5, 0.02)
        # the canopy's steel trusses, and light banks along its leading edge
        for i in range(48):
            t = TAU * i / 48
            x0, y0 = boundary_pt(t, 1.1); x1, y1 = boundary_pt(t, 1.78)
            rib(p.bm, (x0, y0, 0.64), (x1, y1, 0.68), 0.016)
        for f in p.bm.faces:
            for l in f.loops: l[p.cl] = (0.3, 0.32, 0.36, 1)
        lb = bmesh.new()
        for a in range(0, 360, 20):
            x, y = boundary_pt(math.radians(a), 1.08); box(lb, x, y, 0.62, 0.16, 0.04, 0.03, rot=math.radians(a) + math.pi / 2)
        obj_from_bm('Lamps', lb, [mat('LampsN', (1, 0.97, 0.88), 0.3, emit=3.0)])
        for a in (47, 227):     # giant screens in opposite corners, leaning back
            x, y = boundary_pt(math.radians(a), 0.62)
            bs = bmesh.new(); r_ = bmesh.ops.create_cube(bs, size=1); bmesh.ops.scale(bs, vec=(0.6, 0.3, 0.03), verts=r_['verts'])
            bmesh.ops.rotate(bs, verts=r_['verts'], cent=(0, 0, 0), matrix=Euler((math.radians(35), 0, math.radians(a) - math.pi / 2)).to_matrix())
            bmesh.ops.translate(bs, verts=r_['verts'], vec=(x, y, 0.55))
            obj_from_bm('Screen', bs, [mat('Screen', (0.2, 0.45, 0.85), 0.3, emit=2.2)])
        # the players' race on the left wing, and club flags round the top of the lower tier
        x, y = boundary_pt(math.pi, 0.45); p2 = Props(); p2.box(x, y, 0.0, 0.7, 0.1, 0.36, (0.07, 0.07, 0.08)); p2.flat(x + 0.36, y, 0.12, 0.1, (0.9, 0.9, 0.9), z=0.006)
        flagpoles(p2, [boundary_pt(math.radians(a), 0.9) for a in range(15, 360, 30)], [(0.95, 0.75, 0.1), (0.1, 0.3, 0.75), (0.95, 0.95, 0.95), (0.8, 0.1, 0.1)], h=0.8)
        for sgn in (1, -1):                                              # interchange dugouts on the right wing
            x, y = boundary_pt(math.radians(9 * sgn), 0.16); p2.box(x, y, 0, 0.07, 0.3, 0.05, (0.85, 0.9, 0.95), math.radians(9 * sgn)); p2.box(x - 0.05, y, 0, 0.03, 0.26, 0.02, (0.1, 0.25, 0.6), math.radians(9 * sgn))
        x, y = boundary_pt(0, 0.3); p2.box(x, y, 0.2, 0.1, 0.22, 0.02, (0.2, 0.2, 0.22)); p2.box(x, y, 0.22, 0.04, 0.04, 0.04, (0.05, 0.05, 0.05))   # broadcast gantry
        for a, c in ((90, (0.95, 0.75, 0.1)), (270, (0.1, 0.3, 0.75))):   # cheer squads behind each goal: a big banner laid over the seats
            for k in (-1, 0, 1):
                x, y = boundary_pt(math.radians(a + k * 9), 0.3); p2.flat(x, y, 0.22, 0.1, c if k else (0.95, 0.95, 0.95), math.radians(a + k * 9) + math.pi / 2, z=0.14)
        p2.done('Props2')
    if div == 0:
        # Worlds: a full two-tier bowl under a clear perspex dome. Variants (DOME env):
        #   glass  = whole roof glazed, lattice across the ground, daylight
        #   oculus = glazed ring over the stands, open sky above the centre
        #   night  = the glass dome after dark: floodlit, LED rings, glowing ribs
        night = DOME == 'night'
        ground_plane((0.3, 0.31, 0.34), noise=0.05)
        apron(0.08, (0.13, 0.32, 0.08))
        fence(0.09, 0.035, None, boards=[(0.04, 0.05, 0.1), (0.1, 0.55, 0.95), (0.95, 0.95, 0.95), (0.55, 0.2, 0.9)])
        crowd = stands(0, math.pi * 2, 0.12, 1.0, 12, 0.04, 0.9, rng)
        crowd += stands(0, math.pi * 2, 1.18, 0.75, 9, 0.05, 0.85, rng)   # upper tier
        add_crowd(crowd, rng, crowd_pal)
        led_ring(0.105, 0.04, (0.35, 0.75, 1.0), 6.0 if night else 3.0, 0.012)   # LED ribbon on the fence line
        led_ring(1.15, 0.5, (0.55, 0.35, 1.0), 6.0 if night else 3.0)
        open_u = 0.45 if DOME == 'oculus' else None
        glass_dome(RX + 1.25, RY + 1.25, 2.6, 0.5, n_mer=18, n_ring=4, rib_w=0.012, open_u=open_u,
                   tint=(0.97, 0.985, 1.0))
        if DOME == 'oculus':      # a stiff ring beam around the opening
            bm = bmesh.new(); N = 120
            for i in range(N):
                rib(bm, dome_pt(2 * math.pi * i / N, open_u, RX + 1.25, RY + 1.25, 2.6, 0.5), dome_pt(2 * math.pi * (i + 1) / N, open_u, RX + 1.25, RY + 1.25, 2.6, 0.5), 0.05)
            o = obj_from_bm('Oculus', bm, [mat('RingBeam', (0.95, 0.96, 0.98), 0.3)]); DOME_OBJS.append(o)
        if night:
            sc.world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.05, 0.07, 0.12, 1)
            sc.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.35
            for o in sc.objects:
                if o.type == 'LIGHT' and o.data.type == 'SUN': o.data.energy = 0.25
            for a in range(0, 360, 30):                        # floodlights hung from the roof
                x, y = boundary_pt(math.radians(a), 0.6)
                ld = bpy.data.lights.new('Flood', 'SPOT'); ld.energy = 900; ld.spot_size = math.radians(70); ld.color = (1, 0.97, 0.9)
                lo = bpy.data.objects.new('Flood', ld); sc.collection.objects.link(lo); lo.location = (x, y, 2.6)
                lo.rotation_euler = (Vector((0, 0, 0)) - Vector((x, y, 2.6))).to_track_quat('-Z', 'Y').to_euler()
            for o in DOME_OBJS:                                 # ribs pick up a cool glow
                if o.name.startswith('DomeRibs') or o.name.startswith('Oculus'):
                    o.data.materials[0] = mat('RibGlow', (0.7, 0.85, 1.0), 0.3, emit=1.2)
        for a in (60, 240):
            x, y = boundary_pt(math.radians(a), 0.95)
            bs = bmesh.new(); box(bs, x, y, 0.75, 0.55, 0.06, 0.3, rot=math.radians(a) + math.pi / 2)
            obj_from_bm('Screen', bs, [mat('Screen', (0.15, 0.25, 0.45), 0.3, emit=1.2)])
    p.done()
    tag = ('_' + DOME) if div == 0 else ''
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'ground_div%d%s.blend' % (div, tag)))
    # colour pass (the dome throws its shadow but isn't drawn: the game lays it over the top)
    for o in DOME_OBJS: o.visible_camera = False
    sc.render.film_transparent = False
    sc.render.filepath = os.path.join(OUT, 'ground_%d%s.png' % (div, tag))
    bpy.ops.render.render(write_still=True)
    if DOME_OBJS:
        # dome overlay: only the roof, plus the lattice's shadow on the turf, on a transparent film
        for o in DOME_OBJS: o.visible_camera = True
        for o in sc.objects:
            if o.type != 'MESH' or o in DOME_OBJS: continue
            if o.name.startswith('Turf'): o.is_shadow_catcher = True
            else: o.visible_camera = False; o.visible_shadow = False   # only the roof's shadow lands on the turf
        sc.render.film_transparent = True
        sc.render.image_settings.color_mode = 'RGBA'
        sc.render.filepath = os.path.join(OUT, 'dome_%d%s.png' % (div, tag))
        bpy.ops.render.render(write_still=True)
        sc.render.image_settings.color_mode = 'RGB'
        for o in sc.objects:
            if o.type == 'MESH': o.visible_camera = True; o.visible_shadow = True; o.is_shadow_catcher = False
        sc.render.film_transparent = False
    # seat mask pass: seats emit white, everything else black
    white = mat('MaskW', (1, 1, 1)); black = mat('MaskK', (0, 0, 0))
    for m, rgb in ((white, (1, 1, 1)), (black, (0, 0, 0))):
        nt = m.node_tree; nt.nodes.clear()
        out = nt.nodes.new('ShaderNodeOutputMaterial'); em = nt.nodes.new('ShaderNodeEmission')
        em.inputs['Color'].default_value = (*rgb, 1); nt.links.new(em.outputs[0], out.inputs['Surface'])
    for o in sc.objects:
        if o.type != 'MESH': continue
        for i, ms in enumerate(o.data.materials):
            o.data.materials[i] = white if ms and ms.name == 'Seats' else black
    sc.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0
    for o in DOME_OBJS: o.hide_render = True      # the roof is see-through: don't let it hide the seats
    sc.cycles.samples = 4
    sc.render.filepath = os.path.join(OUT, 'seats_%d%s.png' % (div, tag))
    bpy.ops.render.render(write_still=True)

for dv in DIVS:
    build(dv)
print('DONE')
