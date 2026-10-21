"""Re-render a 3D Stage previs headless with the product's own scene.js / webm.js, from the plan stored in the WebM.

usage: python stage_render.py PREVIS.webm OUT.webm [matte]
"matte" renders every cast member white on black (scene.js matte) for guide attention masks.
"""
import base64, sys
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
window.render = async (b64, matte) => {
  const plan = planFromWebM(Uint8Array.from(atob(b64), c => c.charCodeAt(0)));
  const stage = buildStage(plan); stage.roof(true);
  if (matte) stage.matte(true);  // every cast member white on black (scene.js tags them), whatever their coat
  const blob = await encodeCanvas(renderer.domElement, framesOf(plan), FPS, f => { stage.frame(f, plan); renderer.render(stage.scene, stage.camera); }, null, plan);
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let s = ''; for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
};
window.ready = true;
</script></body>"""


def main(src, dest, matte=False):
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
        head = base64.b64encode(Path(src).read_bytes()[:8192]).decode()
        Path(dest).write_bytes(base64.b64decode(page.evaluate("([b, m]) => window.render(b, m)", [head, matte])))
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], len(sys.argv) > 3 and sys.argv[3] == "matte")
    print("ok", sys.argv[2])
