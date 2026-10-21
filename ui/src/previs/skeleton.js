// Pose skeleton pass for the Layout Render: the cast's joints as an OpenPose / DWPose drawing on black. The skeleton
// carries the mannequin's acting into LTX-2.3 Union-Control without its shape (SPEC_10 §7.7): no pose estimation, the
// joints are the mannequin's own, projected through the shot camera.
import * as THREE from 'three';
import { WIDTH, HEIGHT } from './plan.js';

const V = (x, y, z) => new THREE.Vector3(x, y, z);
// Face points on the head joint (figure.js head ellipsoid). His right is -x (figure.js names joints by screen side
// from behind: shoulderL is his right), so OpenPose's right side is the figure's L.
const HEAD = { nose: V(0, 0.094, 0.13), eyeR: V(-0.035, 0.125, 0.092), eyeL: V(0.035, 0.125, 0.092), earR: V(-0.092, 0.11, 0), earL: V(0.092, 0.11, 0) };

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
    return { body, handR: hand('L'), handL: hand('R') };
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

export function drawSkeleton(ctx, people, w = WIDTH, h = HEIGHT) {
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
  }
}
