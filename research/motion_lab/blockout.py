"""Blender 4.3 grey-model previs for S03: observatory proxy, proxy actor reaching for the dial, beacon, real 35mm camera move.
Run: blender -b --python blockout.py -- <out_dir> [lens_mm] [move]
Writes <out>/gray/####.png and <out>/depth/####.png (97 frames, 1280x704, 24 fps)."""
import bpy, math, sys
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
OUT = argv[0]; LENS = float(argv[1]) if len(argv) > 1 else 35.0; MOVE = argv[2] if len(argv) > 2 else "pushin"
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.frame_start, sc.frame_end = 1, 97
sc.render.fps = 24
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 1280, 704, 100


def mat(name, rgb):
    m = bpy.data.materials.new(name); m.diffuse_color = (*rgb, 1.0); return m


GLASS, FLOOR, BRASS, SKIN, COAT, BEAM = (mat("mullion", (.55, .58, .62)), mat("floor", (.30, .31, .33)), mat("console", (.62, .52, .30)),
                                         mat("skin", (.80, .68, .58)), mat("coat", (.22, .23, .25)), mat("beacon", (1, .95, .8)))


def add(prim, name, loc, scale=(1, 1, 1), rot=(0, 0, 0), m=None, **kw):
    getattr(bpy.ops.mesh, prim)(location=loc, rotation=rot, **kw)
    o = bpy.context.active_object; o.name = name; o.scale = scale
    if m: o.data.materials.append(m)
    return o


# Floor and circular glass wall: mullions + rings, open panes so the "outside" background reads as glass.
add("primitive_cylinder_add", "floor", (0, 0, -0.05), (7, 7, .05), m=FLOOR, vertices=96)
R = 6.0
for i in range(28):
    a = 2 * math.pi * i / 28
    add("primitive_cube_add", f"mullion{i}", (R * math.cos(a), R * math.sin(a), 2.6), (.05, .05, 2.6), (0, 0, a), GLASS)
for z in (1.0, 5.2):
    add("primitive_torus_add", f"ring{z}", (0, 0, z), m=GLASS, major_radius=R, minor_radius=.05, major_segments=96, minor_segments=8)
for i in range(14):  # dome ribs
    a = 2 * math.pi * i / 14
    add("primitive_torus_add", f"rib{i}", (0, 0, 5.2), (1, 1, .55), (math.pi / 2, 0, a), GLASS, major_radius=R, minor_radius=.04, major_segments=64, minor_segments=6)

# Curved brass console arc facing the room centre, with a big dial at its middle.
for i in range(-4, 5):
    a = math.radians(90 + i * 9)
    o = add("primitive_cube_add", f"console{i}", (3.1 * math.cos(a), 3.1 * math.sin(a), .5), (.26, .45, .5), (math.radians(-8), 0, a - math.pi / 2), BRASS)
DIAL = Vector((0, 2.7, 1.04))
add("primitive_cylinder_add", "dial", DIAL, (.2, .2, .06), (math.radians(-15), 0, 0), BRASS, vertices=48)

# Distant beacon outside the glass, switched on at frame 70.
beacon = add("primitive_uv_sphere_add", "beacon", (-6, 24, 2.4), (.6, .6, .6), m=BEAM)
for f, s in ((1, 0.001), (68, 0.001), (72, 1.0), (97, 1.0)):
    beacon.scale = (s * .6,) * 3; beacon.keyframe_insert("scale", frame=f)

# Proxy actor: pelvis empty drives a turn; right arm reaches the dial.
root = bpy.data.objects.new("actor", None); sc.collection.objects.link(root); root.location = (-.05, 2.0, 0)
def part(prim, name, loc, scale, m, rot=(0, 0, 0), **kw):
    o = add(prim, name, loc, scale, rot, m, **kw); o.parent = root; return o
part("primitive_cylinder_add", "legL", (-.12, 0, .45), (.09, .09, .45), COAT)
part("primitive_cylinder_add", "legR", (.12, 0, .45), (.09, .09, .45), COAT)
part("primitive_cube_add", "torso", (0, 0, 1.25), (.24, .14, .36), COAT)
part("primitive_uv_sphere_add", "head", (0, 0, 1.78), (.12, .13, .15), SKIN)
part("primitive_cube_add", "nose", (0, .13, 1.78), (.025, .04, .03), SKIN)
part("primitive_cylinder_add", "armL", (-.3, 0, 1.25), (.05, .05, .32), COAT)
shoulder = bpy.data.objects.new("shoulderR", None); sc.collection.objects.link(shoulder); shoulder.parent = root; shoulder.location = (.3, 0, 1.55)
arm = add("primitive_cylinder_add", "armR", (0, 0, -.33), (.05, .05, .33), (0, 0, 0), COAT); arm.parent = shoulder
hand = add("primitive_uv_sphere_add", "handR", (0, 0, -.68), (.06, .06, .06), (0, 0, 0), SKIN); hand.parent = shoulder
# Turn from the window (facing -x) to the console (+y), then reach and hold.
for f, yaw in ((1, math.radians(100)), (26, math.radians(20)), (40, 0), (97, 0)):
    root.rotation_euler = (0, 0, yaw); root.keyframe_insert("rotation_euler", frame=f)
for f, (pitch, roll) in ((1, (0, .1)), (22, (math.radians(10), .1)), (44, (math.radians(66), 0)), (97, (math.radians(66), 0))):
    shoulder.rotation_euler = (pitch, roll, 0); shoulder.keyframe_insert("rotation_euler", frame=f)

# Camera: real lens, target empty; push-in with a slight arc, or orbit / crane variants.
target = bpy.data.objects.new("aim", None); sc.collection.objects.link(target)
cam_data = bpy.data.cameras.new("cam"); cam_data.lens = LENS; cam_data.sensor_width = 36
cam = bpy.data.objects.new("cam", cam_data); sc.collection.objects.link(cam); sc.camera = cam
c = cam.constraints.new("TRACK_TO"); c.target = target; c.track_axis = "TRACK_NEGATIVE_Z"; c.up_axis = "UP_Y"
paths = {
    "pushin": [(1, (-2.6, -0.8, 1.8), (-.05, 2.1, 1.35)), (49, (-0.4, -0.2, 1.8), (.0, 2.4, 1.3)), (97, (1.2, 0.7, 1.95), (.05, 2.55, 1.32))],
    "orbit": [(1, (-2.6, .4, 1.6), (-.05, 2.2, 1.3)), (49, (-.2, -.6, 1.6), (-.05, 2.2, 1.3)), (97, (2.4, .6, 1.6), (-.05, 2.2, 1.3))],
    "crane": [(1, (-1.9, .2, .7), (-.05, 2.2, 1.4)), (97, (-1.4, .6, 3.3), (.0, 2.5, 1.0))],
}
for f, loc, aim in paths[MOVE]:
    cam.location = loc; cam.keyframe_insert("location", frame=f)
    target.location = aim; target.keyframe_insert("location", frame=f)

# Render settings: workbench grey model, plus a normalised depth pass through the compositor.
sc.render.engine = "BLENDER_WORKBENCH"
sh = sc.display.shading; sh.light = "STUDIO"; sh.color_type = "MATERIAL"; sh.show_shadows = True; sh.show_cavity = True
sc.display.shading.background_type = "WORLD"
world = bpy.data.worlds.new("w"); sc.world = world; world.color = (.42, .48, .58)
sc.view_settings.view_transform = "Standard"
vl = sc.view_layers[0]; vl.use_pass_z = True
sc.use_nodes = True; nt = sc.node_tree; nt.nodes.clear()
rl = nt.nodes.new("CompositorNodeRLayers")
comp = nt.nodes.new("CompositorNodeComposite"); nt.links.new(rl.outputs["Image"], comp.inputs["Image"])
norm = nt.nodes.new("CompositorNodeMapRange"); norm.inputs[1].default_value = .5; norm.inputs[2].default_value = 14; norm.inputs[3].default_value = 0; norm.inputs[4].default_value = 1; norm.use_clamp = True
inv = nt.nodes.new("CompositorNodeInvert")
nt.links.new(rl.outputs["Depth"], norm.inputs[0]); nt.links.new(norm.outputs[0], inv.inputs["Color"])
fo = nt.nodes.new("CompositorNodeOutputFile"); fo.base_path = OUT + "/depth/"; fo.format.file_format = "PNG"; fo.format.color_mode = "RGB"
fo.file_slots[0].path = ""
nt.links.new(inv.outputs[0], fo.inputs[0])
sc.render.filepath = OUT + "/gray/"
sc.render.image_settings.file_format = "PNG"
if len(argv) > 3 and argv[3] == "lit":
    # Lit blockout (Eevee): warm low key from the console lamps, cold rim from the window side, dark room.
    sc.render.engine = "BLENDER_EEVEE_NEXT"; sc.eevee.taa_render_samples = 16
    world.use_nodes = True; world.node_tree.nodes["Background"].inputs[0].default_value = (.05, .07, .11, 1); world.node_tree.nodes["Background"].inputs[1].default_value = .6
    for m in bpy.data.materials:
        m.use_nodes = True; m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = m.diffuse_color
    kl = bpy.data.lights.new("key", "AREA"); kl.energy = 900; kl.color = (1.0, .62, .3); kl.size = 1.5
    ko = bpy.data.objects.new("key", kl); sc.collection.objects.link(ko); ko.location = (.3, 2.6, .55); ko.rotation_euler = (math.radians(-110), 0, 0)
    rl_ = bpy.data.lights.new("rim", "SUN"); rl_.energy = 4.0; rl_.color = (.55, .7, 1.0)
    ro = bpy.data.objects.new("rim", rl_); sc.collection.objects.link(ro); ro.rotation_euler = (math.radians(70), 0, math.radians(200))
    sc.use_nodes = False
    sc.render.filepath = OUT + "/lit/"
if len(argv) > 3 and argv[3] == "matte":
    # Matte pass for compositing: R = actor, G = console + dial, B = beacon; alpha 0 = sky seen through the glass.
    sh.light = "FLAT"; sh.show_shadows = False; sh.show_cavity = False
    for m, rgb in ((COAT, (1, 0, 0)), (SKIN, (1, 0, 0)), (BRASS, (0, 1, 0)), (BEAM, (0, 0, 1)), (GLASS, (0, 0, 0)), (FLOOR, (0, 0, 0))):
        m.diffuse_color = (*rgb, 1)
    sc.render.film_transparent = True; sc.render.image_settings.color_mode = "RGBA"
    sc.use_nodes = False
    sc.render.filepath = OUT + "/matte/"
bpy.ops.render.render(animation=True)
