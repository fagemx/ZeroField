"""Blender grey previs for the Updraft oner: canyon floor -> up the cliff -> over the rim into sunrise.

blender -b --python canyon_blockout.py -- <out_dir> [gray|matte] [first_frame] [last_frame]
One continuous camera and balloon path over 961 frames (40 s at 24 fps, 1280x704), cut later into five 193-frame
slices that share their boundary frames (1-193, 193-385, 385-577, 577-769, 769-961).
gray  -> <out>/gray/####.png   workbench grey model
matte -> <out>/matte/####.png  red = the pilot in the basket, black elsewhere (actor attention mask)
Canyon runs along +y (east, toward the sunrise); the river is at x = 0; the rim is at z = 90.
"""
import bpy, bmesh, math, sys
from mathutils import Matrix, Vector, noise

argv = sys.argv[sys.argv.index("--") + 1:]
OUT = argv[0]
MODE = argv[1] if len(argv) > 1 else "gray"
FIRST = int(argv[2]) if len(argv) > 2 and argv[2].isdigit() else 1
LAST = int(argv[3]) if len(argv) > 3 else 1729
FRAMES, LENS, RIM = 1921, 24.0, 90.0  # 40 s move, 8 s hold, 8 s push in to her eye, (transition), 8 s memory, 8 s push in to the child's eye

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.frame_start, sc.frame_end = FIRST, LAST
sc.render.fps = 24
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 1280, 704, 100


def mat(name, rgb):
    m = bpy.data.materials.new(name); m.diffuse_color = (*rgb, 1.0); return m


ROCK, LEDGE, WATER, ENVELOPE, SKIRT, BASKET, PILOT = (mat("rock", (.52, .46, .42)), mat("ledge", (.62, .56, .5)),
                                                      mat("water", (.22, .26, .3)), mat("envelope", (.86, .84, .8)),
                                                      mat("skirt", (.5, .52, .55)), mat("basket", (.45, .38, .3)),
                                                      mat("pilot", (.7, .62, .55)))
CABLE = mat("cable", (.3, .3, .32))


def half_width(z):
    """Canyon half-width at height z: a 60 m floor, widening in terraces to about 85 m at the rim."""
    step = math.floor(z / 11.0)
    return 30.0 + 0.3 * z + 3.0 * step + 2.0 * min(1.0, (z / 11.0 - step) * 4)


def wall(name, side):
    """Vertical rock wall as a displaced grid: x = side * (half_width(z) + noise); ledges every 11 m."""
    ys = [-60 + 2.5 * i for i in range(185)]           # y from -60 to 400
    zs = [-2 + 1.5 * j for j in range(int((RIM + 2) / 1.5) + 2)]
    bm = bmesh.new()
    grid = []
    for y in ys:
        col = []
        bend = 18 * math.sin(y / 140.0) + (0.004 * (y - 200) ** 2 if y > 200 else 0)  # meander; bends away far east
        for z in zs:
            n = noise.noise(Vector((y / 18.0, z / 9.0, side * 3.1))) * 3.2 + noise.noise(Vector((y / 5.0, z / 4.0, side))) * 0.9
            x = side * (half_width(min(z, RIM)) + n) + bend
            col.append(bm.verts.new((x, y, min(z, RIM))))
        grid.append(col)
    for i in range(len(ys) - 1):
        for j in range(len(zs) - 1):
            f = (grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1])
            bm.faces.new(f if side > 0 else tuple(reversed(f)))
    # Plateau beyond the rim.
    edge = [grid[i][-1] for i in range(len(ys))]
    far = [bm.verts.new((side * 700, ys[i], RIM)) for i in range(len(ys))]
    for i in range(len(ys) - 1):
        f = (edge[i], edge[i + 1], far[i + 1], far[i])
        bm.faces.new(f if side < 0 else tuple(reversed(f)))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me); sc.collection.objects.link(o)
    o.data.materials.append(ROCK)
    for p in me.polygons:
        p.use_smooth = True
    return o


def add(prim, name, loc, scale=(1, 1, 1), rot=(0, 0, 0), m=None, parent=None, **kw):
    getattr(bpy.ops.mesh, prim)(location=loc, rotation=rot, **kw)
    o = bpy.context.active_object; o.name = name; o.scale = scale
    if m: o.data.materials.append(m)
    if parent: o.parent = parent
    return o


wall("wall_north", -1)
wall("wall_south", 1)
add("primitive_plane_add", "floor", (0, 170, -0.4), (120, 240, 1), m=LEDGE)
river = add("primitive_plane_add", "river", (0, 170, 0.05), (7, 240, 1), m=WATER)
# An eroded sandstone pinnacle on the north bank, mid-ground, for parallax while the camera rises: a tapering,
# leaning column with a wider cap rock, its radius roughened by noise so it reads as rock, not a stepped tower.
def pinnacle(name, base, height=33.0, segments=20, rings=34):
    bm = bmesh.new()
    loops = []
    for j in range(rings + 1):
        h = height * j / rings
        r = 7.0 * (1 - 0.62 * (h / height) ** 0.8) + (1.6 if h > height * 0.86 else 0)  # cap rock near the top
        lean = Vector((0.12 * h, 0.05 * h, 0))
        ring = []
        for i in range(segments):
            a = 2 * math.pi * i / segments
            n = 1 + 0.22 * noise.noise(Vector((math.cos(a) * 2, math.sin(a) * 2, h / 6))) + 0.08 * math.sin(h * 1.7)
            ring.append(bm.verts.new(Vector(base) + lean + Vector((r * n * math.cos(a), r * n * 1.15 * math.sin(a), h))))
        loops.append(ring)
    for a, b in zip(loops, loops[1:]):
        for i in range(segments):
            bm.faces.new((a[i], a[(i + 1) % segments], b[(i + 1) % segments], b[i]))
    bm.faces.new(loops[-1])
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    me.materials.append(ROCK)
    for poly in me.polygons:
        poly.use_smooth = True
    o = bpy.data.objects.new(name, me); sc.collection.objects.link(o)
    return o


pinnacle("pinnacle0", (-22, 46, -0.5))
# Fallen boulders along the river banks.
for k in range(26):
    y = -20 + k * 11 + 4 * math.sin(k * 2.3)
    x = (9 + 4 * abs(math.sin(k * 1.7))) * (1 if k % 2 else -1)
    s = 1.2 + 1.6 * abs(math.sin(k * 0.9))
    add("primitive_ico_sphere_add", f"boulder{k}", (x, y, s * 0.4), (s * 1.3, s, s * 0.8), m=LEDGE, subdivisions=1)

# Balloon: a lathed teardrop envelope (light upper half, darker lower half: the two colour zones), cables from the
# throat to the basket corners, the burner frame, and the pilot standing in the basket facing east (+y), the sunrise.
balloon = bpy.data.objects.new("balloon", None); sc.collection.objects.link(balloon)
PROFILE = [(9.5, 0.0), (9.2, 2.2), (8.3, 4.2), (6.7, 5.9), (4.5, 7.3), (2.0, 8.2), (0.0, 8.5), (-2.5, 8.3), (-5.0, 7.6),
           (-7.5, 6.5), (-10.0, 5.0), (-12.5, 3.3), (-14.7, 1.8)]


def lathe(name, profile, m_top, m_bottom, segments=48):
    bm = bmesh.new()
    rings = [[bm.verts.new((r * math.cos(2 * math.pi * i / segments), r * math.sin(2 * math.pi * i / segments), z))
              for i in range(segments)] if r > 0 else [bm.verts.new((0, 0, z))] for z, r in profile]
    for a, b in zip(rings, rings[1:]):
        for i in range(segments):
            j = (i + 1) % segments
            face = bm.faces.new((a[0], b[j], b[i]) if len(a) == 1 else (a[i], a[j], b[j], b[i]))
            face.material_index = 0 if face.calc_center_median().z >= 0 else 1
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    me.materials.append(m_top); me.materials.append(m_bottom)
    for poly in me.polygons:
        poly.use_smooth = True
    o = bpy.data.objects.new(name, me); sc.collection.objects.link(o); o.parent = balloon
    return o


lathe("envelope", PROFILE, ENVELOPE, SKIRT)


def rod(name, a, b, radius, m):
    a, b = Vector(a), Vector(b)
    o = add("primitive_cylinder_add", name, (a + b) / 2, (radius, radius, (b - a).length / 2), m=m, parent=balloon, vertices=8)
    o.rotation_mode = "QUATERNION"; o.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(b - a)
    return o


# Hollow wicker basket 1.5 x 1.5 x 1.0 m (floor -19.9, rim -18.9); burner 1.5 m above the rim on four frame rods;
# four cables from the basket corners up to the envelope throat.
for k, (sx, sy) in enumerate(((1, 1), (1, -1), (-1, 1), (-1, -1))):
    rod(f"cable{k}", (.72 * sx, .72 * sy, -18.9), (1.27 * sx, 1.27 * sy, -14.7), .025, CABLE)
    rod(f"frame{k}", (.72 * sx, .72 * sy, -18.9), (.35 * sx, .35 * sy, -17.5), .03, CABLE)
add("primitive_cube_add", "basket", (0, 0, -19.85), (.75, .75, .05), m=BASKET, parent=balloon)
for k, (x, y, sx, sy) in enumerate(((.72, 0, .03, .75), (-.72, 0, .03, .75), (0, .72, .75, .03), (0, -.72, .75, .03))):
    add("primitive_cube_add", f"basket_wall{k}", (x, y, -19.4), (sx, sy, .5), m=BASKET, parent=balloon)
# Twin burner: two small coils side by side on a flat frame (a single big drum was painted as a white bucket).
add("primitive_cube_add", "burner", (0, 0, -17.5), (.36, .22, .02), m=CABLE, parent=balloon)
for side in (-1, 1):
    add("primitive_torus_add", f"burner_coil{side}", (.16 * side, 0, -17.38), m=CABLE, parent=balloon, major_radius=.13,
        minor_radius=.035, major_segments=24, minor_segments=8)
    add("primitive_cylinder_add", f"burner_pot{side}", (.16 * side, 0, -17.38), (.09, .09, .1), m=CABLE, parent=balloon, vertices=12)
# The pilot, 1.72 m, standing at the basket's south-east side and facing east (+y): head and shoulders above the rim.
PX, PY = .2, .0  # 10 cm back from the front corner pole, so the end camera on her right sees her clear of it
# Human proportions, not boxes (a box torso is painted literally): rounded torso and shoulders, arms reaching forward
# with both hands on the front rim.
pilot = [add("primitive_uv_sphere_add", "pilot_head", (PX, PY, -18.28), (.095, .105, .12), m=PILOT, parent=balloon),
         add("primitive_cube_add", "pilot_nose", (PX, PY + .1, -18.29), (.018, .025, .022), m=PILOT, parent=balloon),
         add("primitive_cylinder_add", "pilot_neck", (PX, PY, -18.43), (.045, .045, .05), m=PILOT, parent=balloon),
         add("primitive_uv_sphere_add", "pilot_shoulders", (PX, PY, -18.52), (.23, .12, .07), m=PILOT, parent=balloon),
         add("primitive_cylinder_add", "pilot_body", (PX, PY, -18.8), (.2, .12, .3), m=PILOT, parent=balloon, vertices=24),
         add("primitive_cylinder_add", "pilot_legs", (PX, PY, -19.45), (.17, .1, .4), m=PILOT, parent=balloon, vertices=16)]
for side in (-1, 1):
    shoulder, elbow, hand = (PX + .21 * side, PY, -18.53), (PX + .25 * side, PY + .3, -18.8), (PX + .19 * side, PY + .65, -18.86)
    pilot += [rod(f"pilot_upper{side}", shoulder, elbow, .05, PILOT), rod(f"pilot_fore{side}", elbow, hand, .042, PILOT),
              add("primitive_uv_sphere_add", f"pilot_hand{side}", hand, (.05, .06, .04), m=PILOT, parent=balloon)]
# Her right eye, a dark dot on the head so the push in to it at the end has a target.
pilot.append(add("primitive_uv_sphere_add", "pilot_eye", (PX + .032, PY + .085, -18.26), (.012, .012, .012), m=CABLE, parent=balloon))
for part in pilot:
    for poly in part.data.polygons:
        poly.use_smooth = True
# She is crouched out of sight below the rim until the last slice (a distant figure of a few pixels is painted at the
# wrong size and without her face), then stands up into the light: hidden until RISE starts, then lifted DROP metres.
RISE, DROP = (34.2, 35.6), 0.9
for part in pilot:
    base_z = part.location.z
    part.hide_render = True; part.keyframe_insert("hide_render", frame=1)
    part.hide_render = False; part.keyframe_insert("hide_render", frame=round(RISE[0] * 24) + 1)
    part.location.z = base_z - DROP; part.keyframe_insert("location", index=2, frame=round(RISE[0] * 24) + 1)
    part.location.z = base_z; part.keyframe_insert("location", index=2, frame=round(RISE[1] * 24) + 1)
    part.hide_render = True; part.keyframe_insert("hide_render", frame=1537)  # the memory shot shows only the child
# 54-56 s: she turns her head 30 degrees to her right (the nose and right eye swing round the head), only once the camera
# is close on her eye: a frontal face is painted as a different woman, so she stays in profile while she opens her eyes.
HEAD_TURN = ((1297, 0.0), (1345, 30.0))
nose, eye_obj = bpy.data.objects["pilot_nose"], bpy.data.objects["pilot_eye"]
for f, deg in HEAD_TURN:
    a = math.radians(deg)
    nose.location.x, nose.location.y, nose.rotation_euler.z = PX + .1 * math.sin(a), PY + .1 * math.cos(a), -a
    eye_obj.location.x = PX + .032 * math.cos(a) + .085 * math.sin(a)
    eye_obj.location.y = PY - .032 * math.sin(a) + .085 * math.cos(a)
    for o in (nose, eye_obj):
        o.keyframe_insert("location", index=0, frame=f); o.keyframe_insert("location", index=1, frame=f)
    nose.keyframe_insert("rotation_euler", index=2, frame=f)

# The memory (64-72 s, frames 1537-1729): a seven-year-old girl, 1.2 m, at the back-left of the same basket, her chin at
# the rim, head tipped back to the burner above the basket centre; hidden until then. The adult pilot is her instructor.
CX, CY, CH, LOOK = -.35, -.3, -18.75, math.radians(41)
child = [add("primitive_uv_sphere_add", "child_head", (CX, CY, CH), (.075, .08, .09), m=PILOT, parent=balloon),
         add("primitive_cube_add", "child_nose", (CX + .09 * math.cos(LOOK) * .82, CY + .09 * math.sin(LOOK) * .82, CH + .05),
             (.014, .02, .018), m=PILOT, parent=balloon),
         add("primitive_cylinder_add", "child_neck", (CX, CY, CH - .11), (.035, .035, .03), m=PILOT, parent=balloon),
         add("primitive_uv_sphere_add", "child_shoulders", (CX, CY, CH - .17), (.15, .09, .05), m=PILOT, parent=balloon),
         add("primitive_cylinder_add", "child_body", (CX, CY, CH - .36), (.13, .09, .2), m=PILOT, parent=balloon, vertices=20),
         add("primitive_cylinder_add", "child_legs", (CX, CY, -19.58), (.11, .08, .27), m=PILOT, parent=balloon, vertices=16)]
for side in (-1, 1):
    child.append(rod(f"child_arm{side}", (CX + .14 * side, CY, CH - .18), (CX + .17 * side, CY + .05, CH - .5), .035, PILOT))
for part in child:
    for poly in part.data.polygons:
        poly.use_smooth = True
    part.hide_render = True; part.keyframe_insert("hide_render", frame=1)
    part.hide_render = False; part.keyframe_insert("hide_render", frame=1537)

# Keys, one every 192 frames, joined by a Catmull-Rom spline sampled every frame (C1 at the slice boundaries), easing in
# at the first key and out at the last. The camera looks east up the canyon, toward the dawn sky behind the balloon:
# 0-8 s low over the river; 8-16 s rising off the water; 16-24 s climbing to basket height; 24-32 s rising with the
# basket, closing in; 32-40 s both clear the rim together and the camera settles on the pilot's face in the first sun.
BALLOON_KEYS = [(-4, 80, 34), (-4, 80.5, 46), (-4.2, 81, 60), (-4.3, 81, 76), (-4.5, 81, 96), (-4.5, 81, 110)]
CAM_KEYS = [(6, 0, 3), (8, 22, 9), (12, 38, 30), (16, 50, 57), (10, 66, 79), (-2.12, 82.01, 92.0)]  # end: on her right, 25 deg off the +x axis, clear of the corner pole
# Aim: the glowing envelope early on, the basket while cresting, the pilot's face (head at -17.98 under the centre) last.
AIM_KEYS = [(-4, 80, 40), (-4, 80.5, 50), (-4.2, 81, 62), (-4.3, 81, 70), (-4.5, 81, 84), (-4.3, 81.0, 91.7)]


def catmull(keys, t):
    seg = min(int(t), len(keys) - 2)
    u = t - seg
    p = [Vector(keys[max(0, min(len(keys) - 1, seg + d))]) for d in (-1, 0, 1, 2)]
    # Hermite form: Catmull-Rom tangents inside, zero tangents at the ends (start from rest, settle at the last key).
    m1 = Vector((0, 0, 0)) if seg == 0 else 0.5 * (p[2] - p[0])
    m2 = Vector((0, 0, 0)) if seg + 2 >= len(keys) else 0.5 * (p[3] - p[1])
    h00, h10, h01, h11 = 2 * u ** 3 - 3 * u ** 2 + 1, u ** 3 - 2 * u ** 2 + u, -2 * u ** 3 + 3 * u ** 2, u ** 3 - u ** 2
    return h00 * p[1] + h10 * m1 + h01 * p[2] + h11 * m2


target = bpy.data.objects.new("aim", None); sc.collection.objects.link(target)
cam_data = bpy.data.cameras.new("cam"); cam_data.lens = LENS; cam_data.sensor_width = 36; cam_data.clip_end = 3000
cam = bpy.data.objects.new("cam", cam_data); sc.collection.objects.link(cam); sc.camera = cam
cam_data.clip_start = .1; cam_data.keyframe_insert("clip_start", frame=1200)
cam_data.clip_start = .004; cam_data.keyframe_insert("clip_start", frame=1300)  # the last metres to the eye
c = cam.constraints.new("TRACK_TO"); c.target = target; c.track_axis = "TRACK_NEGATIVE_Z"; c.up_axis = "UP_Y"
# The hold (40-48 s): from rest, the balloon drifts up HOLD_RISE metres and the camera, carried with it, creeps PUSH of the
# way toward her face (2.4 m -> 1.2 m, a close-up), both eased in and out so the shot settles on her.
HOLD_RISE, PUSH = 3.0, 0.5
for f in range(1, FRAMES + 1):
    t = (f - 1) / 192.0
    if t <= 5:
        balloon.location = catmull(BALLOON_KEYS, t)
        cam.location = catmull(CAM_KEYS, t)
        target.location = catmull(AIM_KEYS, t)
    else:
        u = min(1.0, t - 5); e = u * u * (3 - 2 * u)
        lift = Vector((0, 0, HOLD_RISE * e))
        cam5, aim5 = Vector(CAM_KEYS[-1]), Vector(AIM_KEYS[-1])
        balloon.location = Vector(BALLOON_KEYS[-1]) + lift
        cam.location = cam5 + (aim5 - cam5) * PUSH * e + lift
        target.location = aim5 + lift
        if t > 6:
            # 48-56 s: from rest, the camera pushes in to her right eye (after the head turn), ending 3 cm from it, 20 deg
            # off her gaze on the camera's side, still moving: the push goes on into the eye in the next shot.
            u = min(1.0, t - 6); e = u * u * (2 - u)
            base = balloon.location.copy(); rot = Matrix.Rotation(math.radians(0.004 * 1153), 3, "Z")
            eye_end = Vector((PX + .0702, PY + .0576, -18.26))
            cam_end = eye_end + .03 * Vector((math.cos(math.radians(40)), math.sin(math.radians(40)), 0))
            # Start where the hold's take actually ended: its end key framed her face from about 0.45 m, not 1.2 m.
            cam6, aim6 = cam5 + (aim5 - cam5) * PUSH + lift, aim5 + lift
            cam.location = (aim6 + (cam6 - aim6) * (.45 / 1.2)).lerp(base + rot @ cam_end, e)
            target.location = (aim5 + lift).lerp(base + rot @ eye_end, min(1.0, 1.4 * e))
        if t >= 8:
            # 64-72 s (the memory, the same basket): from looking straight up into the burning envelope the camera tilts
            # down past the roaring burner and the instructor's head to the child's upturned face, on her right side, as
            # the adult Noa was framed; it sinks 30 cm as it tilts. 56-64 s is a 2D transition, not rendered here.
            u = min(1.0, t - 8); e = u * u * (3 - 2 * u)
            base = balloon.location.copy(); rot = Matrix.Rotation(math.radians(0.004 * 1153), 3, "Z")
            head = Vector((CX, CY, CH))
            cam_end = head + .5 * Vector((math.cos(LOOK - math.radians(55)), math.sin(LOOK - math.radians(55)), 0)) + Vector((0, 0, -.06))
            d1 = (head + Vector((0, 0, .02)) - cam_end).normalized()
            h = Vector((d1.x, d1.y, 0)).normalized()
            # Start on the far side of the basket from her, looking up at the crown: the crown is centred, the burner sits
            # at the bottom edge, and the start view already has the end view's heading, so the move is a pure tilt (a
            # heading change near the vertical reads as the whole frame rotating).
            start = Vector((0, 0, -18.45)) - .62 * h
            d0 = (Vector((0, 0, 8.5)) - start).normalized()
            cam_l = start.lerp(cam_end, e)
            cam.location = base + rot @ cam_l
            target.location = base + rot @ (cam_l + 2.0 * d0.slerp(d1, e))  # the tilt is even in angle
            if t >= 8.6:
                # 72.6-80 s of the blockout (the oner's end): as the tilt settles, the camera starts to push in on the
                # child's right eye, from rest, ending 3.5 cm from it and still creeping in, the burner's flame in her pupil.
                u = min(1.0, (t - 8.6) / 1.275); e2 = u * u * (2 - u)  # t counts 8 s slices: 72.6 s to the end at 80 s
                face = Vector((math.cos(LOOK), math.sin(LOOK), 0)); right = Vector((math.sin(LOOK), -math.cos(LOOK), 0))
                eye_c = head + .06 * face + .03 * right + Vector((0, 0, .045))
                cam_e = eye_c + .035 * (cam_end - eye_c).normalized()
                aim_e = cam_l + 2.0 * d0.slerp(d1, e)
                cam.location = base + rot @ cam_l.lerp(cam_e, e2)
                target.location = base + rot @ aim_e.lerp(eye_c, min(1.0, 1.4 * e2))
    balloon.keyframe_insert("location", frame=f); cam.keyframe_insert("location", frame=f); target.keyframe_insert("location", frame=f)
    # The balloon turns slowly on its axis, as real balloons do.
    balloon.rotation_euler = (0, 0, math.radians(0.004 * min(f, 1153))); balloon.keyframe_insert("rotation_euler", frame=f)
for o in (balloon, cam, target):
    for fc in o.animation_data.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"

sc.render.engine = "BLENDER_WORKBENCH"
sh = sc.display.shading; sh.light = "STUDIO"; sh.color_type = "MATERIAL"; sh.show_shadows = True; sh.show_cavity = True
sh.background_type = "WORLD"
world = bpy.data.worlds.new("w"); sc.world = world; world.color = (.62, .68, .76)
sc.view_settings.view_transform = "Standard"
sc.render.image_settings.file_format = "PNG"
sc.render.filepath = OUT + "/gray/"
if MODE == "matte":
    sh.light = "FLAT"; sh.show_shadows = False; sh.show_cavity = False
    for m in bpy.data.materials:
        m.diffuse_color = (1, 0, 0, 1) if m is PILOT else (0, 0, 0, 1)
    world.color = (0, 0, 0)
    sc.render.filepath = OUT + "/matte/"

# Burner burns in seconds of the whole shot (start, end); the light rises in 0.25 s and fades over 0.8 s.
BURNS = [(2.5, 4.5), (6.0, 7.4), (10.0, 13.0), (18.0, 20.5), (26.0, 28.0), (35.6, 36.4)]  # last: once she is up


def burn(sec):
    if sec >= 63.5:
        return 0.05  # the memory: low glow, so the envelope interior is not blown out from inside
    level = 0.0
    for a, b in BURNS:
        if a <= sec <= b:
            level = max(level, min(1.0, (sec - a) / 0.25))
        elif b < sec < b + 0.8:
            level = max(level, 1 - (sec - b) / 0.8)
    return level


def sun_up(sec):
    """The first sun reaches the balloon from 27 s and is full by 33 s (the basket clears the rim's shadow)."""
    return min(1.0, max(0.0, (sec - 27.0) / 6.0)) ** 1.5


if MODE.startswith("lit"):
    # Lit previs (Eevee): grey materials, coloured light. Blue-hour sky dome, the envelope glowing from inside with each
    # burn plus a warm unshadowed light at its centre that washes the walls, and a low sun from the east (+y) at the end.
    sc.render.engine = "BLENDER_EEVEE_NEXT"; sc.eevee.taa_render_samples = 16
    sc.view_settings.view_transform = "Standard"
    world.use_nodes = True
    wn, wl = world.node_tree.nodes, world.node_tree.links
    coord, sep, ramp = wn.new("ShaderNodeTexCoord"), wn.new("ShaderNodeSeparateXYZ"), wn.new("ShaderNodeValToRGB")
    wl.new(coord.outputs["Generated"], sep.inputs[0]); wl.new(sep.outputs["Z"], ramp.inputs[0])
    ramp.color_ramp.elements[0].position, ramp.color_ramp.elements[0].color = 0.0, (.9, .55, .38, 1)  # horizon: peach
    ramp.color_ramp.elements[1].position, ramp.color_ramp.elements[1].color = 0.25, (.12, .3, .55, 1)  # zenith: blue
    bg = wn["Background"]; wl.new(ramp.outputs["Color"], bg.inputs["Color"])
    for m in bpy.data.materials:
        m.use_nodes = True
        bsdf = m.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = m.diffuse_color; bsdf.inputs["Roughness"].default_value = 1.0
    glows = []
    for m, color, base in ((ENVELOPE, (1, .58, .24, 1), 1.0), (SKIRT, (1, .66, .34, 1), .7)):
        bsdf = m.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Emission Color"].default_value = color
        glows.append((bsdf.inputs["Emission Strength"], base))
    glow_light = bpy.data.lights.new("glow", "POINT"); glow_light.color = (1, .55, .25); glow_light.shadow_soft_size = 4
    glow_light.use_shadow = False
    gl = bpy.data.objects.new("glow", glow_light); sc.collection.objects.link(gl); gl.parent = balloon; gl.location = (0, 0, -4)
    sun = bpy.data.lights.new("sun", "SUN"); sun.color = (1, .64, .36); sun.angle = math.radians(1.0)
    so = bpy.data.objects.new("sun", sun); sc.collection.objects.link(so); so.rotation_euler = (math.radians(-89.5), 0, 0)  # 0.5 deg: the far rim shades the basket until ~36.5 s
    for f in range(FIRST, LAST + 1):
        sec = (f - 1) / 24.0
        b = burn(sec)
        for socket, base in glows:
            socket.default_value = base * (0.25 + 1.0 * b); socket.keyframe_insert("default_value", frame=f)
        glow_light.energy = 4000 + 90000 * b; glow_light.keyframe_insert("energy", frame=f)
        sun.energy = 6.0 * sun_up(sec); sun.keyframe_insert("energy", frame=f)
        bg.inputs["Strength"].default_value = 0.35 + 0.65 * min(1.0, sec / 34.0); bg.inputs["Strength"].keyframe_insert("default_value", frame=f)
    sc.render.filepath = OUT + "/lit/"
    if MODE == "litstills":
        MODE = "stills"
if MODE == "check":
    # No render: per-slice camera speed, distance to the pilot's head and clearance to the nearest wall (CPU only).
    walls = [bpy.data.objects[n] for n in ("wall_north", "wall_south")]
    head = bpy.data.objects["pilot_head"]
    parts = [bpy.data.objects[n] for n in ("envelope", "basket", "burner", "cable0", "cable1", "cable2", "cable3", "frame0", "frame1", "frame2", "frame3",
                                           "pinnacle0")]

    def clearance(o, p):
        local = o.matrix_world.inverted() @ p
        return (o.matrix_world @ o.closest_point_on_mesh(local)[1] - p).length
    prev = None
    for f in list(range(1, FRAMES + 1, 24)) + [FRAMES]:
        sc.frame_set(f)
        p = cam.matrix_world.translation.copy()
        speed = (p - prev).length if prev else 0.0
        prev = p
        gap = min((w.closest_point_on_mesh(w.matrix_world.inverted() @ p)[1] - w.matrix_world.inverted() @ p).length for w in walls)
        hp = head.matrix_world.translation
        print(f"f{f:4d} cam ({p.x:6.1f},{p.y:6.1f},{p.z:6.1f}) {speed / 1.0:5.2f} m/s  head {(hp - p).length:6.1f} m  wall {gap:5.1f} m  "
              f"balloon z {balloon.matrix_world.translation.z:6.1f}  clear {min(clearance(o, p) for o in parts):5.1f} m")
elif MODE == "stills":
    # Spot frames for a layout review: blender ... -- <out> stills 1,193,385 -> <out>/stills/####.png
    folder = "litstills" if sc.render.engine != "BLENDER_WORKBENCH" else "stills"
    for f in (int(x) for x in argv[2].split(",")):
        sc.frame_set(f); sc.render.filepath = OUT + f"/{folder}/{f:04d}.png"; bpy.ops.render.render(write_still=True)
else:
    bpy.ops.render.render(animation=True)
