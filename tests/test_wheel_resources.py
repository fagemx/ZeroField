"""Source-derived packaging coverage: resources cannot disappear behind stale fixed counts."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('verify_wheel', Path(__file__).resolve().parents[1] / 'scripts/verify_wheel.py')
wheel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wheel)


class WheelResourceTests(unittest.TestCase):
    def test_source_derived_resources_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            files = {'server.py': b'# server', 'run_studio.py': b'# launcher',
                     'db/163_agent_console.sql': b'-- migration',
                     'project_assistant/prompts/coordinator.md': b'Instructions',
                     'project_assistant/studio/comfy_router.py': b'# native module',
                     'workflows/cards/router-new.json': b'{}',
                     'workflows/router/official-new.json': b'{}',
                     'static/projects/assets/current.js': b'console.log(1)',
                     'samples/current.mp4': b'fixture',
                     'skills/README.md': b'# skills',
                     'skills/crew-preproduction/SKILL.md': b'# crew-preproduction'}
            for name, content in files.items():
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            packaged = {name: path.read_bytes() for name, path in wheel.source_resources(source).items()}
            self.assertIn('openbench_data/db/163_agent_console.sql', packaged)
            self.assertIn('project_assistant/studio/comfy_router.py', packaged)
            self.assertIn('openbench_data/skills/crew-preproduction/SKILL.md', packaged)
            self.assertIn('openbench_data/skills/README.md', packaged)
            identity = wheel.verify_identity(packaged.__getitem__, source)
            self.assertEqual((identity['files'], identity['migrations'], identity['cards'], identity['router_schemas']), (11, 1, 1, 1))
            self.assertEqual(identity, wheel.verify_identity(packaged.__getitem__, source))
            for name in ('openbench_data/workflows/router/official-new.json',
                         'openbench_data/skills/crew-preproduction/SKILL.md',
                         'openbench_data/static/projects/assets/current.js'):
                with self.subTest(name=name):
                    original = packaged.pop(name)
                    with self.assertRaisesRegex(SystemExit, 'Missing packaged source resource'):
                        wheel.verify_identity(packaged.__getitem__, source)
                    packaged[name] = original + b'corruption'
                    with self.assertRaisesRegex(SystemExit, 'Packaged source hash mismatch'):
                        wheel.verify_identity(packaged.__getitem__, source)
                    packaged[name] = original


if __name__ == '__main__':
    unittest.main()
