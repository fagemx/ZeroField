"""Script check of the headless previs path (SPEC_20 R27, R28): the real browser, the built solver page, no database.

    python -X utf8 scripts/previs_headless_check.py                   # solve every golden case, render two, check cleanup
    python -X utf8 scripts/previs_headless_check.py --out <folder>    # also keep the contact sheets there (PNG)

Run it after `npm run build --prefix ui` (the page is static/projects/previs-solver.html). It checks that
- every case of tests/fixtures/previs_ops_golden.json solves in the browser to exactly the checked-in plan (the same
  JavaScript as node and the 3D Stage), and every invalid case is refused at the same path;
- a contact sheet renders (PNG, 6 frames) for an observatory and a parallax case, the parallax set image being served
  from memory by the session;
- the page cannot reach the network (a fetch to an outside URL is refused by the session);
- the browser process tree and its profile directory are gone afterwards.
Exit 0 when everything holds; the report is JSON on stdout. Not a unit test: it starts a browser (a few seconds).
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_assistant import headless_previs  # noqa: E402

GOLDEN = ROOT / 'tests' / 'fixtures' / 'previs_ops_golden.json'
RENDER = ('front-closeup-from-the-seed', 'parallax-crane-with-set-image', 'walk-in-toward-the-lens')
# A 2x2 PNG for the parallax card (the session serves it from memory, like a production's set image).
CARD = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000002000000020802000000fdd49a730000001049444154789c6338516103440c100a00'
                     '2bce05f1d07aed5a0000000049454e44ae426082')


def lingering(marker):
    """Processes whose command line still names this session's profile directory."""
    if os.name != 'nt':
        found = subprocess.run(['pgrep', '-f', marker], capture_output=True, text=True, check=False)
        return [line for line in found.stdout.split() if line.strip()]
    script = f"Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -like '*{marker}*' -and $_.ProcessId -ne $PID }} | Select-Object -ExpandProperty ProcessId"
    found = subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True, text=True, check=False)
    return [line.strip() for line in found.stdout.splitlines() if line.strip().isdigit()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', help='keep the rendered contact sheets in this folder')
    args = parser.parse_args(argv)
    golden = json.loads(GOLDEN.read_text(encoding='utf-8'))
    report = {'browser': headless_previs.browser_path(), 'available': headless_previs.availability(), 'cases': [], 'invalid': [],
              'renders': [], 'network': None, 'cleanup': None}
    problems = []
    if not report['available'][0]:
        print(json.dumps(report, indent=1))
        return 2
    started = time.monotonic()
    files = {}
    for case in golden['cases']:
        asset = ((case['input'].get('shot') or {}).get('setAsset') or {}).get('url')
        if asset:
            files[asset] = ('image/png', CARD)
    page = headless_previs.Session(files=files, timeout=180)
    with page:
        profile = page.profile
        report['launchSeconds'] = round(time.monotonic() - started, 2)
        for case in golden['cases']:
            solved = page.solve(case['input'])
            same = solved == case['expect']
            report['cases'].append({'id': case['id'], 'matchesGolden': same})
            if not same:
                problems.append(f"{case['id']}: the browser solved a different plan than the golden file")
        for case in golden['invalid']:
            try:
                page.solve(case['input'])
                path = None
            except headless_previs.Refused as exc:
                path = exc.path
            report['invalid'].append({'id': case['id'], 'path': path, 'expected': case['path']})
            if path != case['path']:
                problems.append(f"{case['id']}: refused at {path}, expected {case['path']}")
        for case in (c for c in golden['cases'] if c['id'] in RENDER):
            began = time.monotonic()
            image, sheet = page.render(case['expect']['plan'], 'check · ' + case['id'])
            width, height = struct.unpack('>II', image[16:24])
            entry = {'id': case['id'], 'bytes': len(image), 'width': width, 'height': height, 'frames': len(sheet['frames']),
                     'seconds': round(time.monotonic() - began, 2)}
            if args.out:
                folder = Path(args.out)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{case['id']}.png").write_bytes(image)
                entry['file'] = str(folder / f"{case['id']}.png")
            report['renders'].append(entry)
            if len(sheet['frames']) != 6 or width < 900:
                problems.append(f"{case['id']}: unexpected contact sheet {width}x{height}, {len(sheet['frames'])} frames")
        served_card = any(url.endswith(next(iter(files), '~')) for url in page.served) if files else None
        outside = page._evaluate("fetch('https://example.com/').then(() => 'reached', () => 'refused')", await_promise=True)
        report['network'] = {'outsideFetch': outside, 'refusedUrls': page.refused[-3:], 'servedSetImage': served_card,
                             'servedFrom': sorted({url.split('/projects/')[0] for url in page.served})}
        if outside != 'refused' or not any('example.com' in url for url in page.refused):
            problems.append('the page reached an outside URL')
    time.sleep(1.0)
    left = lingering(Path(profile).name)
    report['cleanup'] = {'profileDeleted': not Path(profile).exists(), 'processesLeft': left}
    if left or Path(profile).exists():
        problems.append('the browser or its profile outlived the session')
    report['totalSeconds'] = round(time.monotonic() - started, 2)
    report['problems'] = problems
    print(json.dumps(report, indent=1))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
