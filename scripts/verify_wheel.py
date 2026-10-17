"""Verify distributable runtime resources without installing the wheel."""
import re
import sys
import zipfile
from pathlib import Path


def verify(path):
    with zipfile.ZipFile(path) as wheel:
        names = set(wheel.namelist())
        expected = {
            "server.py", "openbench_data/__init__.py", "project_assistant/limb_worker.py",
            "openbench_data/static/projects/index.html",
            "project_assistant/prompts/system.md", "project_assistant/prompts/knowledge.md",
        }
        expected.update(f"openbench_data/db/{name}" for name in (
            "149_project_docs_schema.sql", "151_project_docs_annotations.sql", "153_project_docs_audit.sql",
            "154_project_assistant.sql", "156_project_assistant_conversations.sql", "157_execution.sql", "158_agent_profiles.sql"))
        expected.update('project_assistant/prompts/' + key + '.md' for key in
                        ('coordinator','doc_writer','sheet_ops','qa_critic'))
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
        print(f"Verified {Path(path).name}: SQL, prompts, frontend references and both CLI entry points")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/verify_wheel.py path/to/openbench.whl")
    verify(sys.argv[1])
