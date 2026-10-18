"""Verify distributable runtime resources without installing the wheel."""
import re
import sys
import zipfile
from pathlib import Path


def verify(path):
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
        print(f"Verified {Path(path).name}: SQL, prompts, workflows, samples, frontend and CLI entry points")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/verify_wheel.py path/to/openbench.whl")
    verify(sys.argv[1])
