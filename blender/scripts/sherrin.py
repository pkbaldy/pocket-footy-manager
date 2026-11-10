"""
Pocket Footy Manager — the footy.

A Sherrin-style ball (four red leather panels, dark seams, white lacing) rendered
from the same camera angle as the players. One strip, 48px cells:
  columns 0-7   drop punt — tumbling end over end (backspin), ball travelling to screen right
  columns 8-15  torpedo — spiralling around its long axis
The game rotates the strip to each kick's flight path.

  blender --background --python sherrin.py -- <out_dir> [cell_px]
"""
import bpy, bmesh, math, os, sys
import numpy as np
from mathutils import Euler

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
OUT = os.path.abspath(argv[0] if argv else 'ball'); CELL = int(argv[1]) if len(argv) > 1 else 48
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = 'CYCLES'; scene.cycles.device = 'CPU'; scene.cycles.samples = 32
scene.render.film_transparent = True
scene.render.resolution_x = scene.render.resolution_y = CELL
scene.render.image_settings.file_format = 'PNG'; scene.render.image_settings.color_mode = 'RGBA'
scene.view_settings.view_transform = 'Standard'

# ── leather texture: panels, seams and laces painted onto the sphere's UVs ──────
W, H = 512, 256
img = np.zeros((H, W, 4), dtype=np.float32)
u = np.linspace(0, 1, W, endpoint=False)[None, :].repeat(H, 0)
v = np.linspace(0, 1, H)[:, None].repeat(W, 1)
red = np.array([0.78, 0.16, 0.08]); seam = np.array([0.30, 0.05, 0.03]); white = np.array([0.92, 0.9, 0.86])
col = np.broadcast_to(red, (H, W, 3)).copy()
# subtle grain so the panels aren't flat
col *= (0.93 + 0.07 * np.random.RandomState(3).rand(H, W))[..., None]
# four panel seams running end to end
du = np.minimum.reduce([np.abs(((u - k) + 0.5) % 1 - 0.5) for k in (0.0, 0.25, 0.5, 0.75)])
col[du < 0.006] = seam
# lacing on the seam at u=0.25, through the middle third of the ball
lace_zone = (np.abs(u - 0.25) < 0.035) & (np.abs(v - 0.5) < 0.17)
ladder = (np.floor(v * 70) % 2 == 0)
col[lace_zone & ladder] = white
col[(np.abs(u - 0.25) < 0.004) & (np.abs(v - 0.5) < 0.18)] = white
img[..., :3] = col; img[..., 3] = 1
tex = bpy.data.images.new('Leather', W, H); tex.pixels = img.ravel()

m = bpy.data.materials.new('Sherrin'); m.use_nodes = True
nt = m.node_tree; bsdf = nt.nodes['Principled BSDF']
ti = nt.nodes.new('ShaderNodeTexImage'); ti.image = tex
nt.links.new(ti.outputs['Color'], bsdf.inputs['Base Color'])
bsdf.inputs['Roughness'].default_value = 0.38

# ── the ball: prolate spheroid, long axis along X ───────────────────────────
bm = bmesh.new()
bm.loops.layers.uv.new('UVMap')
bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=1, calc_uvs=True)
# pointier ends than a plain ellipsoid
for vtx in bm.verts:
    z = vtx.co.z
    taper = 1 - 0.18 * (z * z)
    vtx.co.x *= taper; vtx.co.y *= taper
bmesh.ops.scale(bm, vec=(0.09, 0.09, 0.14), verts=bm.verts)
me = bpy.data.meshes.new('Sherrin'); bm.to_mesh(me); bm.free()
for p in me.polygons: p.use_smooth = True
me.materials.append(m)
spin = bpy.data.objects.new('Spin', None); scene.collection.objects.link(spin)
ball = bpy.data.objects.new('Sherrin', me); scene.collection.objects.link(ball)
ball.parent = spin
ball.rotation_euler = Euler((0, math.radians(90), 0))   # long axis → world X (direction of travel)
ball.rotation_mode = 'XYZ'; spin.rotation_mode = 'XYZ'

# ── camera / light — same angle as the player sprites ──────────────────────
cd = bpy.data.cameras.new('Cam'); cd.type = 'ORTHO'; cd.ortho_scale = 0.4
cam = bpy.data.objects.new('Cam', cd); scene.collection.objects.link(cam)
tilt = math.radians(50)
cam.location = (0, -5 * math.cos(tilt), 5 * math.sin(tilt)); cam.rotation_euler = Euler((math.radians(40), 0, 0))
scene.camera = cam
sd = bpy.data.lights.new('Sun', 'SUN'); sd.energy = 3.5
sun = bpy.data.objects.new('Sun', sd); scene.collection.objects.link(sun)
sun.rotation_euler = Euler((math.radians(40), math.radians(-28), math.radians(-35)))
w = bpy.data.worlds.new('W'); scene.world = w; w.use_nodes = True
w.node_tree.nodes['Background'].inputs['Color'].default_value = (0.55, 0.6, 0.55, 1)
w.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.8

# keyframes: 1-8 punt, 9-16 torpedo (so the .blend plays both)
frames = []
for i in range(8):     # end over end: backspin about the axis across the flight (world Y)
    frames.append(Euler((0, math.radians(-i * 22.5), 0)))
for i in range(8):     # spiral about the long axis (world X)
    frames.append(Euler((math.radians(i * 45), 0, 0)))
for f, e in enumerate(frames):
    spin.rotation_euler = e; spin.keyframe_insert('rotation_euler', frame=f + 1)
scene.frame_start, scene.frame_end = 1, len(frames)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'sherrin.blend'))

for f in range(len(frames)):
    scene.frame_set(f + 1)
    scene.render.filepath = os.path.join(OUT, 'ball_%02d.png' % f)
    bpy.ops.render.render(write_still=True)
print('DONE')
