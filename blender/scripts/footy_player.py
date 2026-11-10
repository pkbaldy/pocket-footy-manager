"""
Pocket Footy Manager — player sprite builder.

Builds a stylised AFL player (sleeveless guernsey with collar and armhole trim, a number
on the back, shorts, long socks, boots, hair, a face), animates a 12-frame run cycle,
a 4-frame idle and six 4-frame actions, and renders sprite sheets from the game's
top-down camera angle.

Two sheets are rendered, cell-for-cell identical in layout:
  colour sheet  — the player as seen, with guernsey / shorts / socks rendered
                  white so the game can tint them with any club's colours
  kit sheet     — a data pass the game reads per pixel:
                    R = height up the garment (0 bottom → 1 top)
                    G = angle around the body (0 → 1), so hoops wrap and stripes run vertically
                    B = part: 1.0 guernsey, 0.85 back number, 0.70 trim, 0.5 shorts, 0.25 socks,
                              0.15 hair, 0.08 skin, 0.035 boots  (everything else is left as rendered)
                    A = coverage
                  Skin, hair and boots are rendered near-white too, so the game can give
                  each player their own skin tone, hair colour and boots.

Layout: columns 0-11 = run, 12-15 = idle (12 is the neutral stand), 16+ = actions. Rows = facing direction:
  0 = toward camera (down the screen), 1 = down-right, 2 = right, 3 = up-right, 4 = away (up the screen).
The left-facing directions are the right-facing rows mirrored in game.

Run inside Blender:  blender --background --python footy_player.py -- <out_dir> [cell_px]
or with the bpy module: python footy_player.py <out_dir> [cell_px]
"""
import bpy, bmesh, math, os, sys
from mathutils import Vector, Euler

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
OUT = os.path.abspath(argv[0] if argv else 'sprites')
CELL = int(argv[1]) if len(argv) > 1 else 72
SAVE_BLEND = os.path.join(OUT, 'footy_player.blend')
os.makedirs(OUT, exist_ok=True)

FRAMES = 12            # run cycle
IDLE = 4               # idle frames (first one is the neutral stand)
DIRS = [0, 45, 90, 135, 180]            # yaw: 0 = facing camera (screen down), 90 = screen right, 180 = away
CAM_TILT = 50                            # degrees down from horizontal — matches the ground's look

# ── scene reset ───────────────────────────────────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 32
scene.cycles.use_denoising = False
scene.render.film_transparent = True
scene.render.resolution_x = CELL
scene.render.resolution_y = CELL
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.frame_start, scene.frame_end = 1, FRAMES + IDLE

# ── materials ────────────────────────────────────────────────────────────────
def mat(name, color, rough=0.6):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = (*color, 1)
    b.inputs['Roughness'].default_value = rough
    return m

W = (0.92, 0.92, 0.92)      # tinted in game
M = {
    'skin':   mat('Skin',   W, 0.55),
    'hair':   mat('Hair',   W, 0.8),
    'jumper': mat('Guernsey', W),
    'number': mat('Number', W),
    'trim':   mat('Trim',   W),
    'shorts': mat('Shorts', W),
    'socks':  mat('Socks',  W, 0.75),
    'boots':  mat('Boots',  W, 0.35),
    'sole':   mat('Sole',   (0.03, 0.03, 0.035), 0.5),
    'eye':    mat('Eye',    (0.03, 0.025, 0.02), 0.3),
    'ball':   mat('Leather', (0.62, 0.13, 0.06), 0.4),
}
KIT = {'jumper': 1.0, 'number': 0.85, 'trim': 0.70, 'shorts': 0.5, 'socks': 0.25, 'hair': 0.15, 'skin': 0.08, 'boots': 0.035}

def kit_mat(name, category):
    """Emission material writing (height, angle, category) for the kit data pass."""
    m = bpy.data.materials.new('KIT_' + name)
    m.use_nodes = True
    nt = m.node_tree; n = nt.nodes; l = nt.links
    n.clear()
    out = n.new('ShaderNodeOutputMaterial')
    em = n.new('ShaderNodeEmission'); em.inputs['Strength'].default_value = 1.0
    tc = n.new('ShaderNodeTexCoord')
    sep = n.new('ShaderNodeSeparateXYZ'); l.new(tc.outputs['Generated'], sep.inputs[0])
    # angle around the body = atan2(y-0.5, x-0.5) / 2π + 0.5
    sx = n.new('ShaderNodeMath'); sx.operation = 'SUBTRACT'; sx.inputs[1].default_value = 0.5; l.new(sep.outputs['X'], sx.inputs[0])
    sy = n.new('ShaderNodeMath'); sy.operation = 'SUBTRACT'; sy.inputs[1].default_value = 0.5; l.new(sep.outputs['Y'], sy.inputs[0])
    at = n.new('ShaderNodeMath'); at.operation = 'ARCTAN2'; l.new(sy.outputs[0], at.inputs[0]); l.new(sx.outputs[0], at.inputs[1])
    dv = n.new('ShaderNodeMath'); dv.operation = 'MULTIPLY_ADD'; dv.inputs[1].default_value = 1 / (2 * math.pi); dv.inputs[2].default_value = 0.5
    l.new(at.outputs[0], dv.inputs[0])
    comb = n.new('ShaderNodeCombineXYZ')
    l.new(sep.outputs['Z'], comb.inputs['X'])
    l.new(dv.outputs[0], comb.inputs['Y'])
    comb.inputs['Z'].default_value = category
    l.new(comb.outputs[0], em.inputs['Color'])
    l.new(em.outputs[0], out.inputs['Surface'])
    return m

def holdout_mat():
    m = bpy.data.materials.new('KIT_holdout')
    m.use_nodes = True
    n = m.node_tree.nodes; n.clear()
    out = n.new('ShaderNodeOutputMaterial'); h = n.new('ShaderNodeHoldout')
    m.node_tree.links.new(h.outputs[0], out.inputs['Surface'])
    return m

KITM = {k: kit_mat(k, v) for k, v in KIT.items()}
HOLD = holdout_mat()

# ── geometry helpers ─────────────────────────────────────────────────────────
def empty(name, loc, parent=None):
    e = bpy.data.objects.new(name, None)
    scene.collection.objects.link(e)
    e.empty_display_size = 0.08
    if parent: e.parent = parent
    e.location = loc
    e.rotation_mode = 'XYZ'
    return e

def mesh_obj(name, bm, material, parent, loc=(0, 0, 0), smooth=True):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    if smooth:
        for p in me.polygons: p.use_smooth = True
    me.materials.append(material)
    o = bpy.data.objects.new(name, me)
    scene.collection.objects.link(o)
    o.parent = parent; o.location = loc
    o['part'] = [k for k, v in M.items() if v is material][0]
    return o

def lathe(name, rings, material, parent, loc=(0, 0, 0), segs=18):
    """Smooth body of revolution from rings of (z, rx, ry), capped at both ends."""
    bm = bmesh.new(); rows = []
    for z, rx, ry in rings:
        rows.append([bm.verts.new((rx * math.cos(2 * math.pi * i / segs), ry * math.sin(2 * math.pi * i / segs), z)) for i in range(segs)])
    for j in range(len(rows) - 1):
        for i in range(segs):
            k = (i + 1) % segs
            bm.faces.new((rows[j][i], rows[j][k], rows[j + 1][k], rows[j + 1][i]))
    bm.faces.new(list(reversed(rows[0]))); bm.faces.new(rows[-1])
    return mesh_obj(name, bm, material, parent, loc)

def limb(name, r_top, r_bot, length, material, parent, segs=14, bulge=0.0, bulge_at=0.3):
    """Tapered limb hanging DOWN from its pivot, with rounded ends and an optional muscle bulge."""
    rings = []; N = 9
    for i in range(N + 1):
        t = i / N
        r = r_top + (r_bot - r_top) * t + bulge * math.exp(-((t - bulge_at) / 0.22) ** 2)
        if i == 0: r *= 0.8
        if i == N: r *= 0.85
        rings.append((-length * t, r, r))
    return lathe(name, list(reversed(rings)), material, parent, segs=segs)

def torus(name, R, r, material, parent, loc, rot=(0, 0, 0), scale=(1, 1, 1)):
    bm = bmesh.new(); segs, ring = 20, 6; rows = []
    for i in range(segs):
        a = 2 * math.pi * i / segs
        rows.append([bm.verts.new(((R + r * math.cos(2 * math.pi * j / ring)) * math.cos(a), (R + r * math.cos(2 * math.pi * j / ring)) * math.sin(a), r * math.sin(2 * math.pi * j / ring))) for j in range(ring)])
    for i in range(segs):
        for j in range(ring):
            bm.faces.new((rows[i][j], rows[(i + 1) % segs][j], rows[(i + 1) % segs][(j + 1) % ring], rows[i][(j + 1) % ring]))
    bmesh.ops.scale(bm, vec=scale, verts=bm.verts)
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Euler(rot, 'XYZ').to_matrix())
    return mesh_obj(name, bm, material, parent, loc)

def boxm(name, size, material, parent, loc, smooth=False):
    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    return mesh_obj(name, bm, material, parent, loc, smooth)

def ball(name, r, material, parent, loc, scale=(1, 1, 1), segs=16):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=max(6, segs // 2), radius=r)
    bmesh.ops.scale(bm, vec=scale, verts=bm.verts)
    return mesh_obj(name, bm, material, parent, loc)

# ── the player (≈1.85 units tall, feet at z=0) ───────────────────────────────
root = empty('Player', (0, 0, 0))
hips = empty('Hips', (0, 0, 0.98), root)

# torso / guernsey — one lathed shell: waist, chest, broad shoulders, into the collar
torso_pivot = empty('Chest', (0, 0, 0.02), hips)
torso = lathe('Guernsey', [(0.00, 0.160, 0.112), (0.08, 0.166, 0.116), (0.20, 0.182, 0.124), (0.34, 0.212, 0.134),
                           (0.45, 0.238, 0.134), (0.52, 0.232, 0.120), (0.575, 0.165, 0.100), (0.615, 0.082, 0.074)],
              M['jumper'], torso_pivot, segs=22)
# collar and armhole trim (club's second colour)
torus('Collar', 0.072, 0.016, M['trim'], torso_pivot, (0, 0, 0.612), scale=(1, 0.9, 1))
for sx in (1, -1):
    torus('Armhole' + ('L' if sx > 0 else 'R'), 0.062, 0.013, M['trim'], torso_pivot, (0.226 * sx, 0, 0.505), rot=(0, math.radians(90 - 12 * sx), 0))
# a number on the back (the character faces -Y, so the back is +Y)
boxm('Num1', (0.03, 0.02, 0.135), M['number'], torso_pivot, (-0.04, 0.128, 0.345))
for dx, dz, w, h in ((0.008, 0, 0.022, 0.135), (0.058, 0, 0.022, 0.135), (0.033, 0.057, 0.072, 0.022), (0.033, -0.057, 0.072, 0.022)):   # a boxy "0"
    boxm('Num0', (w, 0.02, h), M['number'], torso_pivot, (dx, 0.128, 0.345 + dz))

neck = limb('Neck', 0.058, 0.062, 0.09, M['skin'], torso_pivot); neck.location = (0, 0, 0.67)
head_pivot = empty('HeadPivot', (0, 0, 0.64), torso_pivot)
head = ball('Head', 0.125, M['skin'], head_pivot, (0, 0, 0.125), (0.90, 0.96, 1.06), segs=20)
ball('Jaw', 0.085, M['skin'], head_pivot, (0, -0.03, 0.055), (0.95, 0.9, 0.8))
ball('Nose', 0.022, M['skin'], head_pivot, (0, -0.122, 0.115), (0.8, 1.0, 1.1), segs=8)
for sx in (1, -1):
    ball('Ear', 0.03, M['skin'], head_pivot, (0.112 * sx, 0.005, 0.12), (0.45, 0.8, 1.0), segs=8)
    ball('Eye', 0.017, M['eye'], head_pivot, (0.045 * sx, -0.107, 0.145), (1, 0.6, 0.9), segs=8)
    boxm('Brow', (0.045, 0.012, 0.011), M['hair'], head_pivot, (0.045 * sx, -0.112, 0.176))
# hair: a cap over the top and back, a swept fringe, short sides
ball('Hair', 0.134, M['hair'], head_pivot, (0, 0.018, 0.158), (0.93, 0.99, 0.84), segs=20)
ball('Fringe', 0.075, M['hair'], head_pivot, (0.012, -0.072, 0.225), (1.25, 0.8, 0.5))
for sx in (1, -1):
    ball('Side', 0.05, M['hair'], head_pivot, (0.095 * sx, 0.01, 0.185), (0.55, 1.2, 0.9), segs=8)

# shorts — a hip shell plus a short leg on each thigh
shorts = lathe('Shorts', [(-0.15, 0.192, 0.132), (-0.06, 0.196, 0.136), (0.02, 0.178, 0.122), (0.06, 0.160, 0.112)], M['shorts'], hips, segs=22)

def leg(side):
    s = 1 if side == 'L' else -1
    thigh_p = empty('Thigh' + side, (0.095 * s, 0, -0.04), hips)
    limb('ShortLeg' + side, 0.098, 0.092, 0.20, M['shorts'], thigh_p)
    limb('ThighSkin' + side, 0.080, 0.060, 0.42, M['skin'], thigh_p, bulge=0.008, bulge_at=0.35)
    knee_p = empty('Knee' + side, (0, 0, -0.42), thigh_p)
    ball('KneeCap' + side, 0.060, M['skin'], knee_p, (0, 0, 0))
    limb('Sock' + side, 0.058, 0.042, 0.40, M['socks'], knee_p, bulge=0.012, bulge_at=0.28)
    ankle_p = empty('Ankle' + side, (0, 0, -0.40), knee_p)
    ball('Boot' + side, 1, M['boots'], ankle_p, (0, -0.055, -0.03), (0.052, 0.128, 0.05))
    ball('BootHeel' + side, 1, M['boots'], ankle_p, (0, 0.02, -0.02), (0.048, 0.06, 0.055), segs=10)
    boxm('Sole' + side, (0.092, 0.235, 0.018), M['sole'], ankle_p, (0, -0.045, -0.076))
    return thigh_p, knee_p, ankle_p

def arm(side):
    s = 1 if side == 'L' else -1
    sh_p = empty('Shoulder' + side, (0.235 * s, 0, 0.52), torso_pivot)
    ball('ShoulderCap' + side, 0.058, M['skin'], sh_p, (0, 0, -0.01))
    limb('UpperArm' + side, 0.054, 0.044, 0.27, M['skin'], sh_p, bulge=0.006, bulge_at=0.3)
    el_p = empty('Elbow' + side, (0, 0, -0.27), sh_p)
    ball('ElbowCap' + side, 0.045, M['skin'], el_p, (0, 0, 0))
    limb('Forearm' + side, 0.044, 0.034, 0.25, M['skin'], el_p, bulge=0.005, bulge_at=0.25)
    ball('Hand' + side, 1, M['skin'], el_p, (0, 0, -0.275), (0.04, 0.046, 0.056))
    return sh_p, el_p

thighL, kneeL, ankleL = leg('L'); thighR, kneeR, ankleR = leg('R')
shL, elL = arm('L'); shR, elR = arm('R')

# Character faces -Y (toward the camera at yaw 0)
# ── run cycle ────────────────────────────────────────────────────────────────
def pose_run(t):
    """t in [0,1). Classic sprint: big thigh drive, heel kick-up, opposite arm pump."""
    a = t * 2 * math.pi
    def legpose(thigh, knee, ankle, ph):
        sw = math.sin(a + ph)                       # +1 = leg forward
        thigh.rotation_euler = Euler((math.radians(-(22 + 40 * sw)), 0, 0))   # 62° drive forward, 18° back
        # heel kicks up during recovery: folds just after toe-off, peaks as the
        # thigh swings through under the hips, then opens out for foot strike
        bend = 22 + 88 * max(0, math.sin(a + ph + 1.1)) ** 1.5
        knee.rotation_euler = Euler((math.radians(bend), 0, 0))
        ankle.rotation_euler = Euler((math.radians(-14 + 26 * sw + 18 * max(0, math.sin(a + ph + 1.1))), 0, 0))   # toe up at strike, pointed at push-off
    legpose(thighL, kneeL, ankleL, 0)
    legpose(thighR, kneeR, ankleR, math.pi)
    def armpose(sh, el, ph, s):
        sw = math.sin(a + ph)
        sh.rotation_euler = Euler((math.radians(-58 * sw), math.radians(-9 * s), 0))
        el.rotation_euler = Euler((math.radians(-80 - 15 * max(0, sw)), 0, 0))
    armpose(shL, elL, math.pi, 1)                  # left arm opposite left leg
    armpose(shR, elR, 0, -1)
    hips.location.z = 0.98 + 0.045 * abs(math.cos(a))   # bounce at each stride
    hips.rotation_euler = Euler((0, 0, math.radians(8 * math.sin(a))))
    torso_pivot.rotation_euler = Euler((math.radians(13 + 2 * math.cos(2 * a)), math.radians(2.5 * math.sin(a)), math.radians(-15 * math.sin(a))))
    head_pivot.rotation_euler = Euler((math.radians(-9), 0, math.radians(10 * math.sin(a))))

def pose_stand():
    for o in (thighL, thighR, kneeL, kneeR, ankleL, ankleR): o.rotation_euler = Euler((0, 0, 0))
    thighL.rotation_euler = Euler((math.radians(-4), math.radians(-3), 0))
    thighR.rotation_euler = Euler((math.radians(4), math.radians(3), 0))
    kneeL.rotation_euler = Euler((math.radians(8), 0, 0)); kneeR.rotation_euler = Euler((math.radians(6), 0, 0))
    shL.rotation_euler = Euler((math.radians(-6), math.radians(-10), 0))
    shR.rotation_euler = Euler((math.radians(4), math.radians(10), 0))
    elL.rotation_euler = Euler((math.radians(-25), 0, 0)); elR.rotation_euler = Euler((math.radians(-20), 0, 0))
    hips.location.z = 0.97
    hips.rotation_euler = Euler((0, 0, 0))
    torso_pivot.rotation_euler = Euler((math.radians(3), 0, 0))
    head_pivot.rotation_euler = Euler((0, 0, 0))

def pose_idle(i):
    """Frame 0 is the neutral stand; the rest breathe and shift weight."""
    pose_stand()
    w = math.sin(2 * math.pi * i / IDLE); c = 1 - math.cos(2 * math.pi * i / IDLE)
    hips.location.z = 0.97 - 0.006 * c
    hips.rotation_euler = Euler((0, math.radians(1.5 * w), math.radians(2.5 * w)))
    torso_pivot.rotation_euler = Euler((math.radians(3 + 1.6 * c), math.radians(-1.5 * w), 0))
    head_pivot.rotation_euler = Euler((math.radians(-1.2 * c), 0, math.radians(-4 * w)))
    shL.rotation_euler = Euler((math.radians(-6 - 3 * c), math.radians(-10 - 2 * c), 0))
    shR.rotation_euler = Euler((math.radians(4 + 3 * w), math.radians(10 + 2 * c), 0))
    kneeL.rotation_euler = Euler((math.radians(8 + 3 * c), 0, 0)); kneeR.rotation_euler = Euler((math.radians(6 + 3 * c), 0, 0))

# Keyframe the clips so the .blend plays as an animation (frames 1-12 run, 13-16 idle)
ANIMATED = [hips, torso_pivot, head_pivot, thighL, thighR, kneeL, kneeR, ankleL, ankleR, shL, shR, elL, elR]
for f in range(FRAMES):
    scene.frame_set(f + 1); pose_run(f / FRAMES)
    for o in ANIMATED:
        o.keyframe_insert('rotation_euler', frame=f + 1); o.keyframe_insert('location', frame=f + 1)
for i in range(IDLE):
    scene.frame_set(FRAMES + 1 + i); pose_idle(i)
    for o in ANIMATED:
        o.keyframe_insert('rotation_euler', frame=FRAMES + 1 + i); o.keyframe_insert('location', frame=FRAMES + 1 + i)

# ── the footy, held during some action frames ─────────────────────────────────
bm = bmesh.new()
bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=1)
for v in bm.verts:
    t = 1 - 0.18 * v.co.z * v.co.z; v.co.x *= t; v.co.y *= t
bmesh.ops.scale(bm, vec=(0.09, 0.09, 0.14), verts=bm.verts)
footy = mesh_obj('Footy', bm, M['ball'], None)
footy.rotation_euler = Euler((math.radians(90), 0, 0))

# ── action poses ─────────────────────────────────────────────────────────────
# Each action is 4 frames. A pose is a dict of joint overrides on top of standing.
# Angles in degrees. Thigh/shoulder X: negative = forward. Knee X: positive = bend.
# Elbow X: negative = bend. Shoulder Y: spreads the arm out sideways (sign per side).
def P(**k): return k
ACTIONS = [
  ('kick', [
    P(tz=5, thL=(-12,0), knL=12, thR=(38,0), knR=75, shL=(-55,-25), elL=-60, shR=(-55,25), elR=-60, ball='hands'),
    P(tz=-6, thL=(4,0), knL=15, thR=(-62,0), knR=12, anR=25, shL=(-40,-55), elL=-20, shR=(25,30), elR=-30),
    P(tz=-14, hz=0.03, thL=(8,0), knL=6, thR=(-100,0), knR=4, anR=35, shL=(-60,-60), elL=-15, shR=(30,40), elR=-25),
    P(tz=4, thL=(5,0), knL=20, thR=(-30,0), knR=35, shL=(-25,-30), elL=-40, shR=(-10,25), elR=-40),
  ]),
  ('handball', [
    P(tz=6, thL=(-18,0), knL=22, thR=(16,0), knR=20, shL=(-62,-5), elL=-75, shR=(40,15), elR=-105, ball='L'),
    P(tz=10, tr=-10, thL=(-18,0), knL=22, thR=(16,0), knR=20, shL=(-55,-5), elL=-75, shR=(-82,0), elR=-12),
    P(tz=10, tr=-18, thL=(-18,0), knL=22, thR=(16,0), knR=20, shL=(-35,-10), elL=-70, shR=(-95,-5), elR=-5),
    P(tz=6, thL=(-10,0), knL=15, thR=(10,0), knR=15, shL=(-20,-10), elL=-50, shR=(-40,10), elR=-40),
  ]),
  ('mark', [
    P(tz=14, hz=-0.12, thL=(-35,0), knL=60, thR=(-35,0), knR=60, anL=-15, anR=-15, shL=(25,-10), elL=-20, shR=(25,10), elR=-20),
    P(tz=0, hz=0.06, thL=(2,0), knL=12, thR=(-75,0), knR=95, shL=(-150,-15), elL=-15, shR=(-150,15), elR=-15, hd=-20),
    P(tz=-4, hz=0.08, thL=(4,0), knL=10, thR=(-80,0), knR=100, shL=(-168,-8), elL=-38, shR=(-168,8), elR=-38, hd=-25, ball='overhead'),
    P(tz=8, hz=-0.08, thL=(-20,0), knL=40, thR=(-10,0), knR=35, shL=(-45,-5), elL=-105, shR=(-45,5), elR=-105, ball='chest'),
  ]),
  ('tackle', [
    P(tz=32, hz=-0.06, thL=(-50,0), knL=65, thR=(22,0), knR=35, shL=(-82,-20), elL=-20, shR=(-82,20), elR=-20, hd=-18),
    P(tz=42, hz=-0.1, thL=(-35,0), knL=55, thR=(35,0), knR=30, shL=(-80,15), elL=-55, shR=(-80,-15), elR=-55, hd=-25),
    P(tz=48, hz=-0.14, thL=(-30,0), knL=60, thR=(42,0), knR=35, shL=(-75,25), elL=-70, shR=(-75,-25), elR=-70, hd=-28),
    P(tz=20, hz=-0.05, thL=(-25,0), knL=40, thR=(20,0), knR=30, shL=(-50,0), elL=-50, shR=(-50,0), elR=-50, hd=-10),
  ]),
  ('ruck', [
    P(tz=10, hz=-0.12, thL=(-35,0), knL=58, thR=(-35,0), knR=58, shL=(15,-15), elL=-30, shR=(15,15), elR=-30),
    P(tz=0, hz=0.07, thL=(4,0), knL=14, thR=(-62,0), knR=90, shL=(-70,-25), elL=-50, shR=(-176,8), elR=-5, hd=-20),
    P(tz=-4, hz=0.09, thL=(6,0), knL=10, thR=(-70,0), knR=95, shL=(-60,-30), elL=-60, shR=(-150,5), elR=-10, hd=-18),
    P(tz=8, hz=-0.06, thL=(-15,0), knL=35, thR=(-5,0), knR=30, shL=(-20,-15), elL=-40, shR=(-40,10), elR=-30),
  ]),
  ('celebrate', [
    P(tz=-6, thL=(-6,-6), knL=10, thR=(6,6), knR=10, shL=(-168,-28), elL=-30, shR=(-168,28), elR=-30, hd=-12),
    P(tz=-4, hz=0.05, thL=(-20,-6), knL=40, thR=(-5,6), knR=30, shL=(-172,-22), elL=-35, shR=(-172,22), elR=-35, hd=-15),
    P(tz=0, thL=(-8,-6), knL=15, thR=(10,6), knR=15, shL=(-30,-25), elL=-95, shR=(-175,15), elR=-45, hd=-10),
    P(tz=0, thL=(8,-6), knL=15, thR=(-8,6), knR=15, shL=(-175,-15), elL=-45, shR=(-30,25), elR=-95, hd=-10),
  ]),
]
ACT_FRAMES = 4

def apply_pose(k):
    pose_stand()
    if 'hz' in k: hips.location.z = 0.97 + k['hz']
    torso_pivot.rotation_euler = Euler((math.radians(k.get('tz', 3)), 0, math.radians(k.get('tr', 0))))
    head_pivot.rotation_euler = Euler((math.radians(k.get('hd', 0)), 0, 0))
    for side, th, kn, an, sh, el in (('L', thighL, kneeL, ankleL, shL, elL), ('R', thighR, kneeR, ankleR, shR, elR)):
        sgn = 1 if side == 'L' else -1
        if 'th' + side in k: x, y = k['th' + side]; th.rotation_euler = Euler((math.radians(x), math.radians(y), 0))
        if 'kn' + side in k: kn.rotation_euler = Euler((math.radians(k['kn' + side]), 0, 0))
        if 'an' + side in k: an.rotation_euler = Euler((math.radians(k['an' + side]), 0, 0))
        if 'sh' + side in k: x, y = k['sh' + side]; sh.rotation_euler = Euler((math.radians(x), math.radians(y), 0))
        if 'el' + side in k: el.rotation_euler = Euler((math.radians(k['el' + side]), 0, 0))

def hand_world(side):
    el = elL if side == 'L' else elR
    return el.matrix_world @ Vector((0, 0, -0.27))

def place_ball(where):
    """Put the footy where the pose says (after the pose is evaluated), or hide it."""
    bpy.context.view_layer.update()
    footy.hide_render = where is None
    if where is None: return
    hl, hr = hand_world('L'), hand_world('R')
    fwd = root.matrix_world.to_3x3() @ Vector((0, -1, 0))
    if where == 'hands': pos = (hl + hr) / 2 + fwd * 0.06
    elif where == 'L': pos = hl + fwd * 0.05
    elif where == 'overhead': pos = (hl + hr) / 2 + Vector((0, 0, 0.05))
    else: pos = (hl + hr) / 2 + fwd * 0.04          # chest
    footy.location = pos
    yaw = root.rotation_euler.z
    footy.rotation_euler = Euler((math.radians(90), 0, yaw))

ACT0 = FRAMES + IDLE + 2
def act_frame(ai, fi): return ACT0 + ai * 5 + fi   # blend frame for action ai, frame fi

for ai, (name, poses) in enumerate(ACTIONS):
    for fi, k in enumerate(poses):
        f = act_frame(ai, fi); scene.frame_set(f); apply_pose(k)
        for o in ANIMATED:
            o.keyframe_insert('rotation_euler', frame=f); o.keyframe_insert('location', frame=f)
        place_ball(k.get('ball'))
        footy.keyframe_insert('location', frame=f); footy.keyframe_insert('hide_render', frame=f)
for f in range(1, FRAMES + IDLE + 1):
    footy.hide_render = True; footy.keyframe_insert('hide_render', frame=f)
for fc in (footy.animation_data.action.fcurves if footy.animation_data else []):
    for kp in fc.keyframe_points: kp.interpolation = 'CONSTANT'
scene.frame_end = act_frame(len(ACTIONS) - 1, ACT_FRAMES - 1)

# ── camera + light ───────────────────────────────────────────────────────────
cam_data = bpy.data.cameras.new('SpriteCam'); cam_data.type = 'ORTHO'; cam_data.ortho_scale = 2.3
cam = bpy.data.objects.new('SpriteCam', cam_data); scene.collection.objects.link(cam)
tilt = math.radians(CAM_TILT)
dist = 10
cam.location = (0, -dist * math.cos(tilt), 1.0 + dist * math.sin(tilt))
cam.rotation_euler = Euler((math.radians(90 - CAM_TILT), 0, 0))
scene.camera = cam

sun_data = bpy.data.lights.new('Sun', 'SUN'); sun_data.energy = 3.2; sun_data.angle = math.radians(8)
sun = bpy.data.objects.new('Sun', sun_data); scene.collection.objects.link(sun)
sun.rotation_euler = Euler((math.radians(40), math.radians(-28), math.radians(-35)))   # from top-left of screen
world = bpy.data.worlds.new('World'); scene.world = world
world.use_nodes = True
world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.55, 0.6, 0.55, 1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.9

bpy.ops.wm.save_as_mainfile(filepath=SAVE_BLEND)

# ── render ───────────────────────────────────────────────────────────────────
parts = [o for o in scene.objects if o.type == 'MESH']
normal_mats = {o.name: o.data.materials[0] for o in parts}

def use_kit_pass(on):
    for o in parts:
        p = o.get('part')
        o.data.materials[0] = (KITM[p] if p in KITM else HOLD) if on else normal_mats[o.name]
    vs = scene.view_settings
    vs.view_transform = 'Raw' if on else 'Standard'
    vs.look = 'None'; vs.exposure = 0; vs.gamma = 1
    scene.cycles.samples = 8 if on else 32
    scene.render.filter_size = 0.01 if on else 1.5   # crisp kit data, soft colour edges

frames_dir = os.path.join(OUT, 'frames'); os.makedirs(frames_dir, exist_ok=True)
PREVIEW = os.environ.get('PREVIEW')        # quick look: a handful of frames, colour only
COLS = [c + 1 for c in range(FRAMES + IDLE)] + [act_frame(ai, fi) for ai in range(len(ACTIONS)) for fi in range(ACT_FRAMES)]
for di, yaw in enumerate(DIRS):
    root.rotation_euler = Euler((0, 0, math.radians(yaw)))
    for c, bf in enumerate(COLS):
        scene.frame_set(bf)
        # the held ball follows the hands, which depend on facing — re-place it per direction
        if bf >= ACT0:
            ai, fi = (bf - ACT0) // 5, (bf - ACT0) % 5
            place_ball(ACTIONS[ai][1][fi].get('ball'))
        bpy.context.view_layer.update()
        if PREVIEW and not (di in (0, 1, 2, 4) and c in (0, 3, 12, 17, 22, 26)): continue
        for kit in ((False,) if PREVIEW else (False, True)):
            use_kit_pass(kit)
            scene.render.filepath = os.path.join(frames_dir, ('kit' if kit else 'col') + '_%d_%d.png' % (di, c))
            bpy.ops.render.render(write_still=True)
use_kit_pass(False)
print('DONE', OUT)
