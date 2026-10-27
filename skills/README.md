# skills/ - workflow manuals for the crew

This folder holds the workflow manuals (SPEC_20 R32): short step-by-step instructions, in the `SKILL.md` format, that tell a planning agent how to do one kind of job in ZeroField. They are plain Markdown with a small header, so the same file works for the built-in crew and for an outside agent connected over MCP.

| Manual | Job |
| --- | --- |
| [`crew-preproduction`](./crew-preproduction/SKILL.md) | Script, then characters/sets/props, then shots and 3D, then continuity, with a human lock between each stage |
| [`shot-beats`](./shot-beats/SKILL.md) | One shot's timed beat-sheet prompt |
| [`previs-blocking`](./previs-blocking/SKILL.md) | 3D blocking for one shot, from structured operations |
| [`continuity-check`](./continuity-check/SKILL.md) | Joins and continuity across adjacent shots and takes |

## How agents get them

The `get_workflow` tool returns a manual by name, for example `crew-preproduction`. It reads `skills/<name>/SKILL.md` from a checkout, or `openbench_data/skills/<name>/SKILL.md` from an installed wheel (`openbench_data.resource_path("skills", name, "SKILL.md")` finds either). The tool is being built; a manual must still be readable as a plain file.

## What the manuals are not

A manual is guidance. It is not a security boundary. Scope, revision checks, production policy, spend limits and the rule that crew output is a proposal are enforced inside the tools, whether or not an agent read or followed a manual (SPEC_20 fixed decisions 8 to 10). If a manual and a tool disagree, the tool wins. Some tools named in the manuals are still under construction; the tool list the server returns is the truth, and every manual tells the agent not to call a tool that is not listed.

## Conventions

- One folder per manual: `skills/<name>/SKILL.md`. The folder name equals `name` in the header.
- The header has exactly three single-line fields: `name`, `description` (what it does, `Use when`, `Not for`) and `version`.
- Required sections, in this order: When to use, Hard rules, Intake questions, Steps, Validation, Human approval, No auto-spend, Failure handling.
- Tool names are written in backticks and must exist: either in `project_assistant/tool_registry.py` or in the SPEC_20 section 4.7 list.
- No camera or lens brand names anywhere. Image models print them onto props.
- Roughly 80 to 160 lines. Put long templates in a `references/` folder beside the manual if one is ever needed.
- `tests/test_skills_content.py` checks all of this. The folder ships in the wheel and sdist (`MANIFEST.in`, `setup.py`, `scripts/verify_wheel.py`).
