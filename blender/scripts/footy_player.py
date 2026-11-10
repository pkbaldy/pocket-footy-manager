"""
Pocket Footy Manager — player sprite builder.

Builds a low-poly AFL player (sleeveless guernsey, shorts, long socks, boots),
animates an 8-frame run cycle plus a standing pose, and renders sprite sheets
from the game's top-down camera angle.

Two sheets are rendered, cell-for-cell identical in layout:
  colour sheet  — the player as seen, with guernsey / shorts / socks rendered
                  white so the game can tint them with any club's colours
  kit sheet     — a data pass the game reads per pixel:
                    R = height up the garment (0 bottom → 1 top)
                    G = angle around the body (0 → 1), so hoops wrap and stripes run vertically
                    B = garment: 1.0 guernsey, 0.5 shorts, 0.25 socks
                    A = coverage

Layout: columns 0-7 = run frames, column 8 = standing. Rows = facing direction:
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

FRAMES = 8
DIRS = [0, 45, 90, 135, 180]            # yaw: 0 = facing camera (screen down), 90 = screen right, 180 = away
CAM_TILT = 50                            # degrees down from horizontal — matches the ground's look

# ── scene reset ───────────────────────────────────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 24
scene.cycles.use_denoising = False
scene.render.film_transparent = True
scene.render.resolution_x = CELL
scene.render.resolution_y = CELL
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.frame_start, scene.frame_end = 1, FRAMES + 1

# ── materials ────────────────────────────────────────────────────────────────
def mat(name, color, rough=0.6):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = (*color, 1)
    b.inputs['Roughness'].default_value = rough
    return m

M = {
    'skin':   mat('Skin',   (0.80, 0.55, 0.40)),
    'hair':   mat('Hair',   (0.10, 0.07, 0.05)),
    'jumper': mat('Guernsey', (0.92, 0.92, 0.92)),   # tinted in game
    'shorts': mat('Shorts', (0.92, 0.92, 0.92)),     # tinted in game
    'socks':  mat('Socks',  (0.92, 0.92, 0.92)),     # tinted in game
    'boots':  mat('Boots',  (0.05, 0.05, 0.06), 0.4),
    'ball':   mat('Leather', (0.55, 0.13, 0.06), 0.45),
}
KIT = {'jumper': 1.0, 'shorts': 0.5, 'socks': 0.25}

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
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    if smooth:
        for p in me.polygons: p.use_smooth = True
    me.materials.append(material)
    o = bpy.data.objects.new(name, me)
    scene.collection.objects.link(o)
    o.parent = parent; o.location = loc
    o['part'] = [k for k, v in M.items() if v is material][0]
    return o

def limb(name, r_top, r_bot, length, material, parent, segs=10):
    """Tapered cylinder hanging DOWN from its pivot (length along -Z)."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segs, radius1=r_bot, radius2=r_top, depth=length)
    bmesh.ops.translate(bm, verts=bm.verts, vec=(0, 0, -length / 2))
    return mesh_obj(name, bm, material, parent)

def ball(name, r, material, parent, loc, scale=(1, 1, 1), segs=12):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=max(6, segs // 2), radius=r)
    bmesh.ops.scale(bm, vec=scale, verts=bm.verts)
    return mesh_obj(name, bm, material, parent, loc)

# ── the player (≈1.85 units tall, feet at z=0) ───────────────────────────────
root = empty('Player', (0, 0, 0))
hips = empty('Hips', (0, 0, 0.98), root)

# torso / guernsey — tapered: narrow waist, broad shoulders, flattened front-to-back
bm = bmesh.new()
bmesh.ops.create_cone(bm, cap_ends=True, segments=14, radius1=0.17, radius2=0.235, depth=0.56)
for v in bm.verts:
    v.co.y *= 0.62
    v.co.z += 0.28
torso_pivot = empty('Chest', (0, 0, 0.02), hips)
torso = mesh_obj('Guernsey', bm, M['jumper'], torso_pivot)
# rounded shoulder caps so the guernsey isn't a can
ball('ShoulderL', 0.075, M['jumper'], torso_pivot, (0.205, 0, 0.53), (1, 0.85, 0.75))
ball('ShoulderR', 0.075, M['jumper'], torso_pivot, (-0.205, 0, 0.53), (1, 0.85, 0.75))

neck = limb('Neck', 0.055, 0.06, 0.08, M['skin'], torso_pivot); neck.location = (0, 0, 0.64)
head_pivot = empty('HeadPivot', (0, 0, 0.64), torso_pivot)
head = ball('Head', 0.125, M['skin'], head_pivot, (0, 0, 0.12), (0.92, 0.95, 1.08))
hair = ball('Hair', 0.132, M['hair'], head_pivot, (0, 0.012, 0.155), (0.95, 0.97, 0.8))

# shorts — hip block + two short legs
bm = bmesh.new()
bmesh.ops.create_cone(bm, cap_ends=True, segments=14, radius1=0.185, radius2=0.17, depth=0.16)
for v in bm.verts: v.co.y *= 0.7
shorts = mesh_obj('Shorts', bm, M['shorts'], hips, (0, 0, -0.02))

def leg(side):
    s = 1 if side == 'L' else -1
    thigh_p = empty('Thigh' + side, (0.095 * s, 0, -0.04), hips)
    short_leg = limb('ShortLeg' + side, 0.092, 0.085, 0.17, M['shorts'], thigh_p)
    thigh = limb('ThighSkin' + side, 0.075, 0.062, 0.42, M['skin'], thigh_p)
    knee_p = empty('Knee' + side, (0, 0, -0.42), thigh_p)
    sock = limb('Sock' + side, 0.06, 0.045, 0.40, M['socks'], knee_p)
    ankle_p = empty('Ankle' + side, (0, 0, -0.40), knee_p)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1)
    bmesh.ops.scale(bm, vec=(0.085, 0.2, 0.075), verts=bm.verts)
    bmesh.ops.translate(bm, verts=bm.verts, vec=(0, -0.05, -0.035))
    boot = mesh_obj('Boot' + side, bm, M['boots'], ankle_p, smooth=False)
    return thigh_p, knee_p, ankle_p

def arm(side):
    s = 1 if side == 'L' else -1
    sh_p = empty('Shoulder' + side, (0.235 * s, 0, 0.52), torso_pivot)
    upper = limb('UpperArm' + side, 0.05, 0.043, 0.27, M['skin'], sh_p)
    el_p = empty('Elbow' + side, (0, 0, -0.27), sh_p)
    fore = limb('Forearm' + side, 0.042, 0.036, 0.25, M['skin'], el_p)
    ball('Hand' + side, 0.042, M['skin'], el_p, (0, 0, -0.27))
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
        ankle.rotation_euler = Euler((math.radians(-10 + 15 * sw), 0, 0))
    legpose(thighL, kneeL, ankleL, 0)
    legpose(thighR, kneeR, ankleR, math.pi)
    def armpose(sh, el, ph, s):
        sw = math.sin(a + ph)
        sh.rotation_euler = Euler((math.radians(-55 * sw), math.radians(-8 * s), 0))
        el.rotation_euler = Euler((math.radians(-80 - 15 * max(0, sw)), 0, 0))
    armpose(shL, elL, math.pi, 1)                  # left arm opposite left leg
    armpose(shR, elR, 0, -1)
    hips.location.z = 0.98 + 0.045 * abs(math.cos(a))   # bounce at each stride
    hips.rotation_euler = Euler((0, 0, math.radians(8 * math.sin(a))))
    torso_pivot.rotation_euler = Euler((math.radians(12), 0, math.radians(-14 * math.sin(a))))
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

# Keyframe the cycle so the .blend plays as an animation (frames 1-8 run, 9 stand)
ANIMATED = [hips, torso_pivot, head_pivot, thighL, thighR, kneeL, kneeR, ankleL, ankleR, shL, shR, elL, elR]
for f in range(FRAMES):
    scene.frame_set(f + 1); pose_run(f / FRAMES)
    for o in ANIMATED:
        o.keyframe_insert('rotation_euler', frame=f + 1); o.keyframe_insert('location', frame=f + 1)
pose_stand()
for o in ANIMATED:
    o.keyframe_insert('rotation_euler', frame=FRAMES + 1); o.keyframe_insert('location', frame=FRAMES + 1)

# ── the footy, held during some action frames ─────────────────────────────────
bm = bmesh.new()
bmesh.ops.create_uvsphere(bm, u_segments=14, v_segments=8, radius=1)
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

def act_frame(ai, fi): return 11 + ai * 5 + fi   # blend frame for action ai, frame fi

for ai, (name, poses) in enumerate(ACTIONS):
    for fi, k in enumerate(poses):
        f = act_frame(ai, fi); scene.frame_set(f); apply_pose(k)
        for o in ANIMATED:
            o.keyframe_insert('rotation_euler', frame=f); o.keyframe_insert('location', frame=f)
        place_ball(k.get('ball'))
        footy.keyframe_insert('location', frame=f); footy.keyframe_insert('hide_render', frame=f)
for f in range(1, FRAMES + 2):
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
    scene.cycles.samples = 8 if on else 24
    scene.render.filter_size = 0.01 if on else 1.5   # crisp kit data, soft colour edges

frames_dir = os.path.join(OUT, 'frames'); os.makedirs(frames_dir, exist_ok=True)
COLS = [c + 1 for c in range(FRAMES + 1)] + [act_frame(ai, fi) for ai in range(len(ACTIONS)) for fi in range(ACT_FRAMES)]
for di, yaw in enumerate(DIRS):
    root.rotation_euler = Euler((0, 0, math.radians(yaw)))
    for c, bf in enumerate(COLS):
        scene.frame_set(bf)
        # the held ball follows the hands, which depend on facing — re-place it per direction
        if bf > FRAMES + 1:
            ai, fi = (bf - 11) // 5, (bf - 11) % 5
            place_ball(ACTIONS[ai][1][fi].get('ball'))
        bpy.context.view_layer.update()
        for kit in (False, True):
            use_kit_pass(kit)
            scene.render.filepath = os.path.join(frames_dir, ('kit' if kit else 'col') + '_%d_%d.png' % (di, c))
            bpy.ops.render.render(write_still=True)
use_kit_pass(False)
print('DONE', OUT)
