"""
Pocket Footy Manager — foil card packs for the Pack Shop.
A crimped, slightly crinkled foil packet, front-on with a little tilt.
  blender --background --python packs.py -- <out_dir> <name> <r,g,b> [w_px]
"""
import bpy, bmesh, math, os, sys, random
from mathutils import Vector, Euler, noise
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
OUT = os.path.abspath(argv[0]); NAME = argv[1]; COL = [float(c) for c in argv[2].split(',')]; W = int(argv[3]) if len(argv) > 3 else 360
os.makedirs(OUT, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'; sc.cycles.samples = 48
sc.render.film_transparent = True
sc.render.resolution_x = W; sc.render.resolution_y = int(W * 1.5)
sc.view_settings.view_transform = 'Standard'
sc.render.image_settings.file_format = 'PNG'; sc.render.image_settings.color_mode = 'RGBA'

# pillow-shaped packet: a subdivided grid, puffed in the middle, crimped at both ends
PW, PH = 1.0, 1.55
bm = bmesh.new()
bmesh.ops.create_grid(bm, x_segments=60, y_segments=90, size=0.5)
for v in bm.verts:
    x, y = v.co.x * 2 * PW / 2, v.co.y * 2 * PH / 2      # -PW/2..PW/2, -PH/2..PH/2
    u, t = x / (PW / 2), y / (PH / 2)                    # -1..1
    crimp = abs(t) > 0.9
    puff = max(0.0, (1 - u * u)) ** 0.6 * max(0.0, (1 - max(0, abs(t) - 0.0) ** 6)) * 0.07
    if crimp: puff = 0.004 * math.sin(u * 60)            # crimped seal ridges
    crinkle = 0.0022 * noise.noise(Vector((x * 9, y * 9, 1.3))) + 0.0008 * noise.noise(Vector((x * 30, y * 30, 7)))
    v.co = Vector((x * (1 - 0.03 * (1 - u * u) * (0 if crimp else 1)), y, puff + crinkle))
me = bpy.data.meshes.new('Pack'); bm.to_mesh(me); bm.free()
for p in me.polygons: p.use_smooth = True
ob = bpy.data.objects.new('Pack', me); sc.collection.objects.link(ob)
ob.rotation_euler = Euler((math.radians(90), 0, math.radians(-12)))

m = bpy.data.materials.new('Foil'); m.use_nodes = True
nt = m.node_tree; b = nt.nodes['Principled BSDF']
b.inputs['Metallic'].default_value = 0.92; b.inputs['Roughness'].default_value = 0.3
# colour band: club colour body, darker crimps, a lighter diagonal sheen stripe
tc = nt.nodes.new('ShaderNodeTexCoord'); sep = nt.nodes.new('ShaderNodeSeparateXYZ')
nt.links.new(tc.outputs['Generated'], sep.inputs[0])
ramp = nt.nodes.new('ShaderNodeValToRGB')
cr = ramp.color_ramp; cr.interpolation = 'EASE'
dark = [c * 0.45 for c in COL]
cr.elements[0].position = 0.0; cr.elements[0].color = (*dark, 1)
cr.elements[1].position = 0.06; cr.elements[1].color = (*COL, 1)
e = cr.elements.new(0.94); e.color = (*COL, 1)
e = cr.elements.new(1.0); e.color = (*dark, 1)
nt.links.new(sep.outputs['Y'], ramp.inputs[0])
nt.links.new(ramp.outputs['Color'], b.inputs['Base Color'])
me.materials.append(m)

cd = bpy.data.cameras.new('C'); cd.lens = 85
cam = bpy.data.objects.new('C', cd); sc.collection.objects.link(cam)
cam.location = (0, -5.0, 0); cam.rotation_euler = Euler((math.radians(90), 0, 0)); sc.camera = cam
for loc, en, sz in (((-2.6, -3, 1.8), 160, 1.6), ((2.8, -2.5, -0.8), 45, 3.0), ((0.6, -3.5, 2.8), 40, 0.8)):
    ld = bpy.data.lights.new('L', 'AREA'); ld.energy = en; ld.size = sz
    lo = bpy.data.objects.new('L', ld); sc.collection.objects.link(lo); lo.location = loc
    lo.rotation_euler = (Vector((0, 0, 0)) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
w = bpy.data.worlds.new('W'); sc.world = w; w.use_nodes = True
w.node_tree.nodes['Background'].inputs['Color'].default_value = (0.035, 0.04, 0.045, 1)
w.node_tree.nodes['Background'].inputs['Strength'].default_value = 1.0
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, NAME + '.blend'))
sc.render.filepath = os.path.join(OUT, NAME + '.png')
bpy.ops.render.render(write_still=True)
print('DONE')
