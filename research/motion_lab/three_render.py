"""Render three_block.html frames headless with Playwright (GPU via ANGLE), then encode gray/depth mp4."""
import base64, subprocess, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
out = Path(sys.argv[1]); move = sys.argv[2] if len(sys.argv) > 2 else "pushin"; lens = float(sys.argv[3]) if len(sys.argv) > 3 else 35
for k in ("gray", "depth"): (out / k).mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-angle=d3d11", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={"width": 1280, "height": 704})
    pg.goto((Path(__file__).parent / "three_block.html").resolve().as_uri()); pg.wait_for_function("window.ready === true", timeout=30000)
    for f in range(1, 98):
        for k in ("gray", "depth"):
            data = pg.evaluate(f"window.renderFrame({f}, '{k}', '{move}', {lens})")
            (out / k / f"{f:04d}.png").write_bytes(base64.b64decode(data.split(",", 1)[1]))
    b.close()
for k in ("gray", "depth"):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "24", "-i", str(out / k / "%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", str(out / f"{k}.mp4")], check=True)
print("ok")
