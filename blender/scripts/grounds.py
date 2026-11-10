"""
Pocket Footy Manager — home grounds, one per division.

An aerial view of everything around the oval, rendered straight down so the
playing surface lines up exactly with the game's ground (the game draws the
turf and markings itself on top). 1 Blender unit = 100 ground units.

  4 Outback League   red dirt, picket fence, utes and cars around the boundary, gums, tin clubrooms
  3 Country League   grass banks, a small grandstand, cars, trees, scoreboard
  2 State League     stands down both wings, terraces behind the goals, four light towers
  1 National League  a full bowl, tiered stands, roof rim, light towers, big screens

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

def stands(t0, t1, off0, depth, rows, rise, occupancy, rng, roof=0.0):
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
        obj_from_bm('Roof', rb, [mat('Roof', (0.86, 0.87, 0.88), 0.4)])
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

# ── divisions ───────────────────────────────────────────────────────────────
def build(div):
    global SEATS, CONCRETE
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
    if div == 4:
        ground_plane((0.55, 0.3, 0.16), noise=0.25)                        # red dirt
        apron(0.06, (0.42, 0.42, 0.2))                                     # dry grass run-off
        fence(0.07, 0.05, (0.95, 0.95, 0.92), posts=True)
        cars_ring(rng, 0.1, 0.62, 70, [(0, TAU)], car_cols)
        trees(rng, 26, corners, 0.75, 1.6, 1.3)
        building(-1.72, 2.62, 0.5, 0.26, 0.09, math.radians(-40), (0.8, 0.78, 0.7), (0.3, 0.5, 0.3))   # clubrooms
        building(1.85, -2.62, 0.22, 0.16, 0.07, math.radians(40), (0.7, 0.68, 0.6), (0.6, 0.62, 0.64))  # canteen
        box_sc = bmesh.new(); box(box_sc, 1.95, 2.55, 0, 0.32, 0.05, 0.16, rot=math.radians(-35)); obj_from_bm('Scoreboard', box_sc, [mat('Board', (0.12, 0.12, 0.12))])
    elif div == 3:
        ground_plane((0.22, 0.36, 0.14), noise=0.18)                       # grass surrounds
        apron(0.06, (0.2, 0.38, 0.12))
        fence(0.07, 0.05, (0.95, 0.95, 0.92), posts=True)
        crowd = stands(math.radians(160), math.radians(200), 0.12, 0.42, 6, 0.04, 0.55, rng, roof=0.55)   # grandstand on the left wing
        # grassy banks with people sitting around the fence
        bank = []
        for _ in range(900):
            t = rng.uniform(0, TAU)
            if math.radians(155) < t < math.radians(205): continue
            x, y = boundary_pt(t, rng.uniform(0.1, 0.24))
            if in_frame(x, y): bank.append((x, y, 0))
        add_crowd(crowd + bank, rng, crowd_pal)
        cars_ring(rng, 0.32, 0.9, 60, corners, car_cols)
        trees(rng, 20, corners, 0.9, 1.7, 1.2)
        building(1.98, 2.5, 0.42, 0.22, 0.09, math.radians(-38), (0.85, 0.83, 0.78), (0.55, 0.15, 0.12))
        box_sc = bmesh.new(); box(box_sc, -1.95, -2.55, 0, 0.4, 0.06, 0.2, rot=math.radians(-35)); obj_from_bm('Scoreboard', box_sc, [mat('Board', (0.1, 0.1, 0.1))])
    elif div == 2:
        ground_plane((0.5, 0.5, 0.48), noise=0.08)                          # concrete concourse
        apron(0.08, (0.14, 0.33, 0.09))
        fence(0.09, 0.035, None, boards=[(0.08, 0.15, 0.4), (0.95, 0.95, 0.95), (0.7, 0.1, 0.1), (0.1, 0.1, 0.1)])
        crowd = []
        crowd += stands(math.radians(-38), math.radians(38), 0.12, 1.3, 14, 0.035, 0.62, rng, roof=0.35)
        crowd += stands(math.radians(142), math.radians(218), 0.12, 1.3, 14, 0.035, 0.62, rng, roof=0.35)
        crowd += stands(math.radians(52), math.radians(128), 0.12, 0.9, 9, 0.025, 0.45, rng)     # terraces behind the goals
        crowd += stands(math.radians(232), math.radians(308), 0.12, 0.9, 9, 0.025, 0.45, rng)
        add_crowd(crowd, rng, crowd_pal)
        for a in (40, 140, 220, 320):
            x, y = boundary_pt(math.radians(a), 0.72); light_tower(x, y)
    else:
        ground_plane((0.45, 0.45, 0.44), noise=0.05)
        apron(0.08, (0.13, 0.32, 0.08))
        fence(0.09, 0.035, None, boards=[(0.05, 0.05, 0.08), (0.95, 0.75, 0.1), (0.95, 0.95, 0.95), (0.1, 0.3, 0.75)])
        crowd = stands(0, math.pi * 2, 0.12, 1.5, 18, 0.04, 0.85, rng, roof=0.32)
        add_crowd(crowd, rng, crowd_pal)
        for a in (30, 90, 150, 210, 270, 330):
            x, y = boundary_pt(math.radians(a), 1.05); light_tower(x, y, 1.6)
        for a in (55, 235):     # big screens in opposite pockets
            x, y = boundary_pt(math.radians(a), 0.55)
            bs = bmesh.new(); box(bs, x, y, 0.6, 0.5, 0.06, 0.28, rot=math.radians(a) + math.pi / 2)
            obj_from_bm('Screen', bs, [mat('Screen', (0.15, 0.2, 0.3), 0.3, emit=0.8)])
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'ground_div%d.blend' % div))
    # colour pass
    sc.render.film_transparent = False
    sc.render.filepath = os.path.join(OUT, 'ground_%d.png' % div)
    bpy.ops.render.render(write_still=True)
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
    sc.cycles.samples = 4
    sc.render.filepath = os.path.join(OUT, 'seats_%d.png' % div)
    bpy.ops.render.render(write_still=True)

for dv in DIVS:
    build(dv)
print('DONE')
