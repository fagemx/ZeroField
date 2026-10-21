// Pose skeleton pass for the Layout Render: the cast's joints as an OpenPose / DWPose drawing on black. The skeleton
// carries the mannequin's acting into LTX-2.3 Union-Control without its shape (SPEC_10 §7.7): no pose estimation, the
// joints are the mannequin's own, projected through the shot camera.
import * as THREE from 'three';
import { WIDTH, HEIGHT } from './plan.js';

const V = (x, y, z) => new THREE.Vector3(x, y, z);
// Face points on the head joint (figure.js head ellipsoid). His right is -x (figure.js names joints by screen side
// from behind: shoulderL is his right), so OpenPose's right side is the figure's L.
const HEAD = { nose: V(0, 0.094, 0.13), eyeR: V(-0.035, 0.125, 0.092), eyeL: V(0.035, 0.125, 0.092), earR: V(-0.092, 0.11, 0), earL: V(0.092, 0.11, 0) };

// The 68 face landmarks (iBUG 300-W order: jaw, brows, nose, eyes, lips) on the head ellipsoid's front, moved by an
// expression (plan.js EXPRESSIONS). Head-local metres, +x the person's left; nose points keep their own depth.
const EGG = { cy: 0.115, cz: 0.01, rx: 0.092, ry: 0.118, rz: 0.103 };
export function faceLandmarks(e = {}) {
  const { jaw = 0, wide = 0, smile = 0, brow = 0, inner = 0, eyes = 0 } = e, pts = [];
  for (let i = 0; i <= 16; i++) {  // jaw: the person's right ear line, round the chin, to the left
    const s = i / 16, down = Math.sin(Math.PI * s);
    pts.push([-0.078 * Math.cos(Math.PI * s), 0.112 - 0.107 * down ** 0.9 - jaw * 0.03 * down ** 2]);
  }
  for (const side of [-1, 1]) for (let i = 0; i < 5; i++) {  // brows, outer to inner on the right, inner to outer on the left
    const t = side < 0 ? i / 4 : 1 - i / 4, innerW = t;  // t: 1 at the inner end
    const x = side * (0.062 - 0.05 * t) * (1 + Math.min(0, brow) * 0.12 * innerW);
    pts.push([x, 0.150 + 0.008 * Math.sin(Math.PI * (0.25 + 0.6 * t)) + brow * 0.01 + inner * 0.012 * innerW ** 2 + Math.min(0, brow) * 0.005 * innerW]);
  }
  const nose = [[0, 0.135, 0.105], [0, 0.12, 0.112], [0, 0.105, 0.122], [0, 0.092, 0.132], [-0.018, 0.079, 0.112], [-0.009, 0.076, 0.118], [0, 0.074, 0.12], [0.009, 0.076, 0.118], [0.018, 0.079, 0.112]];
  const h = Math.max(0.0012, 0.009 * (eyes >= 0 ? 1 + 0.8 * eyes : 1 + 0.85 * eyes)), w = 0.026;
  // Each eye from its -x corner over the top (36 is the right eye's outer corner, 42 the left eye's inner one).
  const eye = cx => [[-w / 2, 0], [-w / 6, h / 2], [w / 6, h / 2], [w / 2, 0], [w / 6, -h / 2], [-w / 6, -h / 2]].map(([x, y]) => [cx + x, 0.125 + y]);
  const eyeR = eye(-0.035), eyeL = eye(0.035);
  const mw = 0.05 * (1 + wide * 0.35), cy = 0.06, drop = jaw * 0.034, lift = smile * 0.008;
  const lower = x => cy - drop * Math.cos(Math.PI * x / mw), corner = cy - jaw * 0.012 + lift;
  const outer = [[-mw / 2, corner], [-mw / 3, cy + 0.006 + jaw * 0.004], [-mw / 8, cy + 0.009 + jaw * 0.004], [0, cy + 0.008 + jaw * 0.004], [mw / 8, cy + 0.009 + jaw * 0.004],
    [mw / 3, cy + 0.006 + jaw * 0.004], [mw / 2, corner], [mw / 3, lower(mw / 3) - 0.007], [mw / 8, lower(mw / 8) - 0.01], [0, lower(0) - 0.011], [-mw / 8, lower(mw / 8) - 0.01], [-mw / 3, lower(mw / 3) - 0.007]];
  const inside = [[-mw * 0.4, corner], [-mw / 8, cy + 0.002 + jaw * 0.004], [0, cy + 0.002 + jaw * 0.004], [mw / 8, cy + 0.002 + jaw * 0.004], [mw * 0.4, corner],
    [mw / 8, lower(mw / 8) - 0.002], [0, lower(0) - 0.002], [-mw / 8, lower(mw / 8) - 0.002]];
  const onEgg = ([x, y], sink = 0) => V(x, y, EGG.cz + EGG.rz * Math.sqrt(Math.max(0.02, 1 - (x / EGG.rx) ** 2 - ((y - EGG.cy) / EGG.ry) ** 2)) - sink);
  return [...pts.map(p => onEgg(p)), ...nose.map(p => V(...p)), ...eyeR.map(p => onEgg(p, 0.008)), ...eyeL.map(p => onEgg(p, 0.008)), ...outer.map(p => onEgg(p)), ...inside.map(p => onEgg(p, 0.004))];
}

// Every cast member's keypoints in pixels for the current pose and camera: OpenPose's 18 body points [x, y, visible]
// and 21 per hand. Eyes and nose only when the face is toward the camera, an ear when its side is.
export function poseKeypoints(scene, camera) {
  // The camera is not in the scene: without a WebGL render in between, its view matrix would still be last frame's.
  scene.updateMatrixWorld(true); camera.updateMatrixWorld();
  const px = w => { const n = w.clone().project(camera); return [(n.x + 1) / 2 * WIDTH, (1 - n.y) / 2 * HEIGHT, n.z < 1 && Math.abs(n.x) < 1.2 && Math.abs(n.y) < 1.2 ? 1 : 0]; };
  return scene.children.filter(o => o.userData.actor).map(root => {
    const k = {}; root.traverse(o => { if (o.userData.kp) k[o.userData.kp] = o; });
    const at = (o, local = V(0, 0, 0)) => o.localToWorld(local.clone());
    const head = k.head, q = head.getWorldQuaternion(new THREE.Quaternion());
    const toCam = camera.position.clone().sub(at(head)).normalize();
    const face = V(0, 0, 1).applyQuaternion(q).dot(toCam), right = V(-1, 0, 0).applyQuaternion(q).dot(toCam);
    const shown = { nose: face > 0.05, eyeR: face > 0.1 && right > -0.65, eyeL: face > 0.1 && -right > -0.65, earR: right > -0.3, earL: -right > -0.3 };
    const hd = n => { const p = px(at(head, HEAD[n])); p[2] = p[2] && shown[n] ? 1 : 0; return p; };
    const sR = at(k.shoulderL), sL = at(k.shoulderR);
    const body = [hd('nose'), px(sR.clone().add(sL).multiplyScalar(0.5)), px(sR), px(at(k.elbowL)), px(at(k.wristL)), px(sL), px(at(k.elbowR)), px(at(k.wristR)),
      px(at(k.hipL)), px(at(k.kneeL)), px(at(k.ankleL)), px(at(k.hipR)), px(at(k.kneeR)), px(at(k.ankleR)), hd('eyeR'), hd('eyeL'), hd('earR'), hd('earL')];
    const finger = (f, s) => [0, 1, 2].map(j => px(at(k[`f${f}_${j}${s}`]))).concat([px(at(k[`f${f}_2${s}`], V(0, -k[`f${f}_2${s}`].userData.tip, 0)))]);
    const hand = s => [px(at(k['wrist' + s])), ...[0, 1, 2, 3, 4].flatMap(f => finger(f, s))];
    // A detector finds the whole face or none of it: all 68 points while the face is turned toward the camera.
    const faceOn = face > 0.3, f68 = faceLandmarks(root.userData.face).map(p => { const q = px(at(head, p)); q[2] = q[2] && faceOn ? 1 : 0; return q; });
    return { body, handR: hand('L'), handL: hand('R'), face: f68 };
  });
}

// controlnet_aux's DWPose drawing (util.draw_bodypose / draw_handpose): 1-based limbs zipped with 18 colours, limbs at
// 60 %, joints at full colour, hand edges round the hue wheel with blue points. Sizes are DWPose's at ~768 px wide,
// scaled to the 1280 px render.
const LIMBS = [[2, 3], [2, 6], [3, 4], [4, 5], [6, 7], [7, 8], [2, 9], [9, 10], [10, 11], [2, 12], [12, 13], [13, 14], [2, 1], [1, 15], [15, 17], [1, 16], [16, 18], [3, 17]];
const COLORS = [[255, 0, 0], [255, 85, 0], [255, 170, 0], [255, 255, 0], [170, 255, 0], [85, 255, 0], [0, 255, 0], [0, 255, 85], [0, 255, 170], [0, 255, 255],
  [0, 170, 255], [0, 85, 255], [0, 0, 255], [85, 0, 255], [170, 0, 255], [255, 0, 255], [255, 0, 85], [255, 0, 170]];
const HAND_EDGES = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [0, 9], [9, 10], [10, 11], [11, 12], [0, 13], [13, 14], [14, 15], [15, 16],
  [0, 17], [17, 18], [18, 19], [19, 20]];
const K = 1.6, STICK = Math.round(4 * K);
const rgb = c => `rgb(${c[0]},${c[1]},${c[2]})`;

// face: also draw the 68 face points (DWPose's white dots); off in the product until the 4090 shows they help (SPEC_10 §7.9).
export function drawSkeleton(ctx, people, w = WIDTH, h = HEIGHT, face = false) {
  ctx.fillStyle = '#000'; ctx.fillRect(0, 0, w, h);
  for (const p of people) {
    const b = p.body;
    LIMBS.forEach(([i, j], n) => {
      const [x1, y1, v1] = b[i - 1], [x2, y2, v2] = b[j - 1];
      if (!v1 || !v2) return;
      ctx.fillStyle = rgb(COLORS[n].map(c => Math.floor(c * 0.6)));
      ctx.beginPath(); ctx.ellipse((x1 + x2) / 2, (y1 + y2) / 2, Math.max(Math.hypot(x1 - x2, y1 - y2) / 2, 0.5), STICK, Math.atan2(y1 - y2, x1 - x2), 0, 2 * Math.PI); ctx.fill();
    });
    b.forEach(([x, y, v], n) => { if (v) { ctx.fillStyle = rgb(COLORS[n]); ctx.beginPath(); ctx.arc(x, y, STICK, 0, 2 * Math.PI); ctx.fill(); } });
    for (const hand of [p.handR, p.handL]) {
      if (!hand[0][2]) continue;
      ctx.lineWidth = Math.round(2 * K);
      HAND_EDGES.forEach(([i, j], e) => {
        ctx.strokeStyle = `hsl(${e / HAND_EDGES.length * 360},100%,50%)`;
        ctx.beginPath(); ctx.moveTo(hand[i][0], hand[i][1]); ctx.lineTo(hand[j][0], hand[j][1]); ctx.stroke();
      });
      ctx.fillStyle = 'rgb(0,0,255)';
      for (const [x, y] of hand) { ctx.beginPath(); ctx.arc(x, y, Math.round(2.5 * K), 0, 2 * Math.PI); ctx.fill(); }
    }
    if (face && p.face) {
      ctx.fillStyle = '#fff';
      for (const [x, y, v] of p.face) if (v) { ctx.beginPath(); ctx.arc(x, y, Math.round(3 * K), 0, 2 * Math.PI); ctx.fill(); }
    }
  }
}
