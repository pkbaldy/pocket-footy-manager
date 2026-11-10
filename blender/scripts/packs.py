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
sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'; sc.cycles.samples = 64
sc.render.film_transparent = True
sc.render.resolution_x = W; sc.render.resolution_y = int(W * 1.5)
sc.view_settings.view_transform = 'Standard'
sc.render.image_settings.file_format = 'PNG'; sc.render.image_settings.color_mode = 'RGBA'

# pillow-shaped packet: a subdivided grid, puffed in the middle, crimped at both ends
PW, PH = 1.0, 1.55
bm = bmesh.new()
bmesh.ops.create_grid(bm, x_segments=120, y_segments=180, size=0.5)
for v in bm.verts:
    x, y = v.co.x * 2 * PW / 2, v.co.y * 2 * PH / 2      # -PW/2..PW/2, -PH/2..PH/2
    u, t = x / (PW / 2), y / (PH / 2)                    # -1..1
    crimp = abs(t) > 0.9
    puff = max(0.0, (1 - u * u)) ** 0.6 * max(0.0, (1 - max(0, abs(t) - 0.0) ** 6)) * 0.07
    if crimp: puff = 0.004 * math.sin(u * 60)            # crimped seal ridges
    crinkle = 0.0022 * noise.noise(Vector((x * 9, y * 9, 1.3))) + 0.0008 * noise.noise(Vector((x * 30, y * 30, 7)))
    d = (x / 0.15) ** 2 + ((y + 0.3) / 0.21) ** 2                     # an embossed footy below the label
    emb = 0.0 if crimp else 0.005 * (1 if 0.75 < d < 1.0 else 0) + 0.003 * (1 if abs(x) < 0.007 and abs(y + 0.3) < 0.15 else 0)
    v.co = Vector((x * (1 - 0.03 * (1 - u * u) * (0 if crimp else 1)), y, puff + crinkle + emb))
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

# ── a printed panel on the front: a satin window with an embossed footy, plus a holo strip ──
def panel(name, w, h, z, rgb, rough, metal, emb=0.0):
    bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=24, y_segments=36, size=0.5)
    for v in bm.verts:
        x, y = v.co.x * w, v.co.y * h
        u, t = x / (PW / 2), y / (PH / 2)
        puff = max(0.0, (1 - u * u)) ** 0.6 * 0.07 + 0.004
        # embossed footy outline in the middle of the panel
        e = 0.0
        if emb:
            d = (x / 0.16) ** 2 + (y / 0.25) ** 2
            e = emb * (1 if 0.72 < d < 1.0 else 0) + emb * 0.6 * (1 if abs(x) < 0.008 and abs(y) < 0.18 else 0)
        v.co = Vector((x, y, puff + z + e))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for p_ in me.polygons: p_.use_smooth = True
    mm = bpy.data.materials.new(name); mm.use_nodes = True
    bb = mm.node_tree.nodes['Principled BSDF']
    bb.inputs['Base Color'].default_value = (*rgb, 1); bb.inputs['Roughness'].default_value = rough; bb.inputs['Metallic'].default_value = metal
    me.materials.append(mm)
    o = bpy.data.objects.new(name, me); sc.collection.objects.link(o); o.parent = ob
    o.location = (0, -0.52, 0)
    return mm

holo = panel('Holo', 0.96, 0.045, 0.003, (1, 1, 1), 0.12, 1.0)
# rainbow foil: colour follows the viewing angle
nt2 = holo.node_tree; b2 = nt2.nodes['Principled BSDF']
lw = nt2.nodes.new('ShaderNodeLayerWeight'); lw.inputs['Blend'].default_value = 0.6
tc2 = nt2.nodes.new('ShaderNodeTexCoord'); sx2 = nt2.nodes.new('ShaderNodeSeparateXYZ'); nt2.links.new(tc2.outputs['Generated'], sx2.inputs[0])
add = nt2.nodes.new('ShaderNodeMath'); add.operation = 'ADD'; nt2.links.new(lw.outputs['Facing'], add.inputs[0]); nt2.links.new(sx2.outputs['X'], add.inputs[1])
fr = nt2.nodes.new('ShaderNodeMath'); fr.operation = 'FRACT'; nt2.links.new(add.outputs[0], fr.inputs[0])
hr = nt2.nodes.new('ShaderNodeValToRGB'); e_ = hr.color_ramp.elements
e_[0].color = (1.0, 0.35, 0.5, 1); e_[1].color = (0.3, 0.6, 1.0, 1)
for pos, c in ((0.33, (1.0, 0.9, 0.3, 1)), (0.66, (0.35, 1.0, 0.6, 1))):
    n_ = e_.new(pos); n_.color = c
nt2.links.new(fr.outputs[0], hr.inputs[0]); nt2.links.new(hr.outputs[0], b2.inputs['Base Color'])
nt2.links.new(hr.outputs[0], b2.inputs['Emission Color']); b2.inputs['Emission Strength'].default_value = 0.35

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
