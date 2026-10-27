"""Verify wheel resources and optional frozen-source / installed runtime identity."""
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path


def source_resources(source):
    source = Path(source)
    resources = {"server.py": source / "server.py", "run_studio.py": source / "run_studio.py"}
    for package in ("project_assistant", "project_docs", "openbench_data"):
        resources.update({p.relative_to(source).as_posix(): p for p in (source / package).rglob("*.py")
                          if "__pycache__" not in p.parts})
    for pattern in ("db/*.sql", "project_assistant/prompts/*.md", "project_assistant/provider_catalog.json", "workflows/*.json", "workflows/*.md",
                    "workflows/cards/*.json", "workflows/router/*.json", "samples/*.png", "samples/*.mp4",
                    "samples/*.md", "samples/*.py", "skills/**/*.md", "static/projects/**/*"):
        for path in source.glob(pattern):
            if path.is_file():
                relative = path.relative_to(source).as_posix()
                key = relative if relative.startswith("project_assistant/") else "openbench_data/" + relative
                resources[key] = path
    return resources


def verify_identity(read, source):
    resources = source_resources(source)
    for name, path in resources.items():
        try:
            actual = read(name)
        except (KeyError, FileNotFoundError):
            raise SystemExit("Missing packaged source resource: " + name)
        if hashlib.sha256(actual).digest() != hashlib.sha256(path.read_bytes()).digest():
            raise SystemExit("Packaged source hash mismatch: " + name)
    return {"files": len(resources), "migrations": len(list(Path(source).glob("db/*.sql"))),
            "cards": len(list(Path(source).glob("workflows/cards/*.json"))),
            "router_schemas": len(list(Path(source).glob("workflows/router/*.json"))),
            "sha256": hashlib.sha256("\n".join(name + ":" + hashlib.sha256(path.read_bytes()).hexdigest()
                                              for name, path in sorted(resources.items())).encode()).hexdigest()}


def verify_installed(root, source):
    root = Path(root).resolve()
    identity = verify_identity(lambda name: (root / name).read_bytes(), source)
    # Ignore PYTHONPATH/cwd but retain installed user-site runtime dependencies; fetch nothing.
    modules = ("server", "run_studio", "project_docs.repository", "project_docs.console_http",
               "project_assistant.agent_console_service", "project_assistant.console_deployments",
               "project_assistant.agent_runtime", "project_assistant.studio_tools",
               "project_assistant.outcome_grader", "project_assistant.execution_governance",
               "project_assistant.studio.comfy_router", "project_assistant.studio.comfy_mcp",
               "project_assistant.studio.model_router", "project_assistant.limb_worker")
    code = """
import importlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(root))
modules = [importlib.import_module(n) for n in sys.argv[2:]]
assert all(pathlib.Path(m.__file__).resolve().is_relative_to(root) for m in modules)
from openbench_data import resource_path
from project_docs import repository
from project_assistant import limb_worker, prompting
from project_assistant.studio import comfy_router
for name in repository.SCHEMA_FILES:
    assert (repository.SCHEMA_DIR / name).resolve().is_relative_to(root)
    assert (repository.SCHEMA_DIR / name).read_text(encoding='utf-8').strip()
assert all(prompting.load())
cards = list(resource_path('workflows', 'cards').glob('*.json'))
for card in cards:
    assert limb_worker.load_studio_card(card.stem)['card_id'] == card.stem
for model in comfy_router.MODELS:
    schema = resource_path('workflows', 'router', model.replace('/', '--') + '.json')
    assert schema.resolve().is_relative_to(root)
    assert json.loads(schema.read_text(encoding='utf-8'))['paths']
    card = limb_worker.load_studio_card('router-' + model.split('/')[1])
    values = {n['nodeId'] + '.' + n['fieldName']: n['defaultValue'] for n in card['nodes']}
    if model.startswith('higgsfield/'):
        values.update({'input.image_1': 'fixture-image', 'input.video_url': 'fixture-video'})
    nodes = comfy_router._nodes({'production_policy': 'hybrid_studio'}, card, values)
    media = {n['fieldName']: nodes[n['fieldName']] for n in card['nodes']
             if n['fieldType'] in ('IMAGE', 'VIDEO', 'AUDIO') and nodes[n['fieldName']] != 'None'}
    comfy_router._native(card, nodes, media)  # Pure installed schema validation, no network or grants.
assert resource_path('static', 'projects', 'index.html').resolve().is_relative_to(root)
print('Installed imports:', len(modules), 'migrations:', len(repository.SCHEMA_FILES),
      'loaded cards:', len(cards), 'native schemas:', len(comfy_router.MODELS))
"""
    subprocess.run([sys.executable, "-E", "-P", "-c", code, str(root), *modules], cwd=root.parent, check=True, timeout=30)
    print("Installed source identity:", json.dumps(identity, sort_keys=True))


def verify(path, source=None):
    with zipfile.ZipFile(path) as wheel:
        names = set(wheel.namelist())
        expected = {
            "server.py", "run_studio.py", "openbench_data/__init__.py", "project_assistant/limb_worker.py",
            "openbench_data/static/projects/index.html",
            "project_assistant/prompts/system.md", "project_assistant/prompts/knowledge.md",
            "project_assistant/prompts/runtime.md",
        }
        expected.update(f"openbench_data/db/{name}" for name in (
            "149_project_docs_schema.sql", "151_project_docs_annotations.sql", "153_project_docs_audit.sql",
            "154_project_assistant.sql", "156_project_assistant_conversations.sql", "157_execution.sql", "158_agent_profiles.sql",
            "159_agent_orchestration.sql", "160_agent_races.sql", "161_agent_comment_routes.sql"))
        expected.update('project_assistant/prompts/' + key + '.md' for key in
                        ('coordinator','doc_writer','sheet_ops','qa_critic'))
        expected.update('project_assistant/' + name + '.py' for name in
                        ('agent_registry','agent_policy','agent_runtime','orchestrator','orchestration_store',
                         'orchestration_service','orchestration_flow','orchestration_limb','comment_routing',
                         'acp_bridge','mcp_stdio','tool_host'))
        expected.update("openbench_data/workflows/" + name + ".json" for name in
                        ("flux3_klein_soul_cast", "ltx25_cinema_shot", "ltx25_openjutsu_v2v"))
        expected.update("openbench_data/skills/" + name + "/SKILL.md" for name in
                        ("crew-preproduction", "shot-beats", "previs-blocking", "continuity-check"))
        expected.add("openbench_data/skills/README.md")
        expected.update("openbench_data/samples/" + name for name in
                        ("cast_kael.png", "set_observatory.png", "keyframe_s01.png", "keyframe_s02.png",
                         "shot_s01.mp4", "shot_s02.mp4", "openjutsu_source.mp4", "openjutsu_remastered.mp4", "openjutsu_split.mp4", "first_frame_vfx01.png", "motion_structure_vfx01.mp4", "anchor_keyframe_vfx01.png"))
        missing = expected - names
        if missing:
            raise SystemExit("Wheel is missing resources: " + ", ".join(sorted(missing)))
        html = wheel.read("openbench_data/static/projects/index.html").decode("utf-8")
        references = re.findall(r'(?:src|href)="/projects/(assets/[^"?]+)', html)
        if not references or not any(ref.endswith(".js") for ref in references):
            raise SystemExit("Bundled index does not reference a built JavaScript entry point")
        for relative in references:
            if "openbench_data/static/projects/" + relative not in names:
                raise SystemExit("Bundled index references missing asset: " + relative)
        entries = [n for n in names if n.endswith(".dist-info/entry_points.txt")]
        if len(entries) != 1 or "openbench = server:main" not in wheel.read(entries[0]).decode():
            raise SystemExit("Wheel has no openbench console entry point")
        if "openbench-worker = project_assistant.limb_worker:main" not in wheel.read(entries[0]).decode():
            raise SystemExit("Wheel has no openbench-worker console entry point")
        if "zerofield-studio = run_studio:main" not in wheel.read(entries[0]).decode():
            raise SystemExit("Wheel has no zerofield-studio console entry point")
        if source:
            print("Wheel source identity:", json.dumps(verify_identity(wheel.read, source), sort_keys=True))
        print(f"Verified {Path(path).name}: SQL, prompts, workflows, skills, samples, frontend and CLI entry points")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", nargs="?")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--installed-root", type=Path)
    args = parser.parse_args()
    if args.installed_root:
        if not args.source:
            parser.error("--installed-root requires --source")
        verify_installed(args.installed_root, args.source)
    elif args.wheel:
        verify(args.wheel, args.source)
    else:
        parser.error("provide a wheel or --installed-root")
