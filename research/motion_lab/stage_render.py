"""Re-render a 3D Stage previs headless with the product's own scene.js / webm.js, from the plan stored in the WebM.

usage: python stage_render.py PREVIS.webm|PLAN.json OUT.webm|OUT.json [matte|pose]
A PLAN.json renders a plan written by hand or by a lab script (performance keys, poses, cast) instead of a stored one.
"matte" renders every cast member white on black (scene.js matte) for guide attention masks.
"pose" writes OUT.json instead of a video: per frame, every cast member's OpenPose keypoints in pixels (pose_skeleton.py
draws them): 18 body points [x, y, visible] with the eyes, nose and ears only where the face or that side faces the
camera, and 21 per hand. figure.js names its joints by side of the screen from behind (shoulderL is at -x, his right),
so OpenPose's right is the figure's L.
"""
import base64, json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PAGE = """<!doctype html><body style="margin:0"><script type="importmap">{"imports":{"three":"/ui/node_modules/three/build/three.module.js"}}</script>
<script type="module">
import * as THREE from 'three';
import { buildStage, prepareRenderer } from '/ui/src/previs/scene.js';
import { framesOf, WIDTH, HEIGHT, FPS } from '/ui/src/previs/plan.js';
import { encodeCanvas, planFromWebM } from '/ui/src/previs/webm.js';
const renderer = prepareRenderer(new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true }));
renderer.setPixelRatio(1); renderer.setSize(WIDTH, HEIGHT, false); document.body.appendChild(renderer.domElement);
window.render = async (b64, matte, json) => {
  const plan = json ? JSON.parse(json) : planFromWebM(Uint8Array.from(atob(b64), c => c.charCodeAt(0)));
  const stage = buildStage(plan); stage.roof(true);
  if (matte) stage.matte(true);  // every cast member white on black (scene.js tags them), whatever their coat
  const blob = await encodeCanvas(renderer.domElement, framesOf(plan), FPS, f => { stage.frame(f, plan); renderer.render(stage.scene, stage.camera); }, null, plan);
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let s = ''; for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
};
const V = (x, y, z) => new THREE.Vector3(x, y, z);
const HEAD = { nose: V(0, 0.094, 0.13), eyeR: V(-0.035, 0.125, 0.092), eyeL: V(0.035, 0.125, 0.092), earR: V(-0.092, 0.11, 0), earL: V(0.092, 0.11, 0) };
window.keypoints = async json => {
  const plan = JSON.parse(json), stage = buildStage(plan), cam = stage.camera, out = [];
  for (let f = 0; f < framesOf(plan); f++) {
    stage.frame(f, plan); stage.scene.updateMatrixWorld(true);
    const px = w => { const n = w.clone().project(cam); return [(n.x + 1) / 2 * WIDTH, (1 - n.y) / 2 * HEIGHT, n.z < 1 && Math.abs(n.x) < 1.2 && Math.abs(n.y) < 1.2 ? 1 : 0]; };
    const people = stage.scene.children.filter(o => o.userData.actor).map(root => {
      const k = {}; root.traverse(o => { if (o.userData.kp) k[o.userData.kp] = o; });
      const at = (o, local = V(0, 0, 0)) => o.localToWorld(local.clone());
      const head = k.head, q = head.getWorldQuaternion(new THREE.Quaternion()), hp = at(head);
      const toCam = cam.position.clone().sub(hp).normalize(), face = V(0, 0, 1).applyQuaternion(q).dot(toCam), right = V(-1, 0, 0).applyQuaternion(q).dot(toCam);
      const shown = { nose: face > 0.05, eyeR: face > 0.1 && right > -0.65, eyeL: face > 0.1 && -right > -0.65, earR: right > -0.3, earL: -right > -0.3 };
      const hd = n => { const p = px(at(head, HEAD[n])); p[2] &&= shown[n] ? 1 : 0; return p; };
      const sR = at(k.shoulderL), sL = at(k.shoulderR);
      const body = [hd('nose'), px(sR.clone().add(sL).multiplyScalar(0.5)), px(sR), px(at(k.elbowL)), px(at(k.wristL)), px(sL), px(at(k.elbowR)), px(at(k.wristR)),
        px(at(k.hipL)), px(at(k.kneeL)), px(at(k.ankleL)), px(at(k.hipR)), px(at(k.kneeR)), px(at(k.ankleR)), hd('eyeR'), hd('eyeL'), hd('earR'), hd('earL')];
      const hand = s => [px(at(k['wrist' + s]))].concat(...[0, 1, 2, 3, 4].map(f => [0, 1, 2].map(j => px(at(k[`f${f}_${j}${s}`]))).concat([px(at(k[`f${f}_2${s}`], V(0, -k[`f${f}_2${s}`].userData.tip, 0)))])));
      return { body, handR: hand('L'), handL: hand('R') };
    });
    out.push(people);
  }
  return JSON.stringify(out);
};
window.ready = true;
</script></body>"""


def plan_of(webm):
    head = Path(webm).read_bytes()[:8192].decode("latin-1")
    return json.JSONDecoder().raw_decode(head, head.index("zf-plan:") + len("zf-plan:"))[0]


def main(src, dest, mode=None):
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-angle=d3d11", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1280, "height": 704})

        def serve(route):
            path = route.request.url.split("http://localhost:9", 1)[1].split("?")[0]
            if path == "/":
                return route.fulfill(body=PAGE, content_type="text/html")
            return route.fulfill(path=str(ROOT / path.lstrip("/")), content_type="text/javascript")

        page.route("http://localhost:9/**", serve)
        page.goto("http://localhost:9/")
        page.wait_for_function("window.ready === true", timeout=60000)
        json_plan = Path(src).read_text(encoding="utf-8") if str(src).endswith(".json") else None
        head = "" if json_plan else base64.b64encode(Path(src).read_bytes()[:8192]).decode()
        if mode == "pose":
            Path(dest).write_text(page.evaluate("j => window.keypoints(j)", json_plan or json.dumps(plan_of(src))), encoding="utf-8")
        else:
            Path(dest).write_bytes(base64.b64decode(page.evaluate("([b, m, j]) => window.render(b, m, j)", [head, mode == "matte", json_plan])))
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    print("ok", sys.argv[2])
