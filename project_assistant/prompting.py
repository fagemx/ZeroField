"""組一輪的提示（跟 10/14 測試版同一個版面）；從知識包解析每一題「答完整的標準」給畫面的工作台。"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

PROMPTS = Path(__file__).resolve().parent / "prompts"
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SPEAKER = {"assistant": "Assistant", "lead": "Owner reply"}


def load() -> tuple[str, str]:
    return ((PROMPTS / "system.md").read_text(encoding="utf-8"),
            (PROMPTS / "knowledge.md").read_text(encoding="utf-8"))


def load_agent(profile) -> tuple[str,str]:
    baseline=(PROMPTS/'runtime.md').read_text(encoding='utf-8')
    return baseline+'\n\n'+profile.get('system_prompt',''),profile.get('knowledge_pack','')


KIND_LABEL = {"image": "Image, subject to production privacy settings", "sheet": "Excel",
              "doc": "Document (Word / PDF)", "text": "Text file"}


def build_prompt(*, system: str, knowledge: str, today: dt.date, owner_name: str, owner_role: str = "",
                 history: list[dict],
                 pending: list[dict], message: str, guard_notes: list[str], attachments=()) -> str:
    instructions, turn = build_parts(system=system, knowledge=knowledge, today=today, owner_name=owner_name,
                                     owner_role=owner_role, history=history, pending=pending, message=message,
                                     guard_notes=guard_notes, attachments=attachments)
    return instructions + "\n" + turn


def build_parts(*, system: str, knowledge: str, today: dt.date, owner_name: str, owner_role: str = "",
                history: list[dict],
                pending: list[dict], message: str, guard_notes: list[str], attachments=()) -> tuple[str, str]:
    """(固定的規則＋知識包, 這一輪的內容)。直接呼叫模型時，固定的那段當 instructions，模型那端可以快取。
    attachments：這一輪附的檔案 [{kind, name, extracted}]；圖片本身另外跟著訊息送，這裡只寫是哪張。"""

    instructions = "\n".join([system, "\n## Knowledge Pack\n", knowledge])
    parts = [f"\n## Current Context\nToday is {today.isoformat()} ({WEEKDAYS[today.weekday()]}). "
             f"You are in Studio Assistant, speaking privately with {owner_name}" + (f" ({owner_role})" if owner_role else "") + "."]
    if history:
        parts.append("\n## Conversation History (use for continuity; do not repeat it)")
        for item in history:
            files = item.get("files") or []
            body = item["body"] + (f" (attached: {', '.join(files)})" if files else "")
            parts.append(f"{SPEAKER.get(item['role'], owner_name)}：{body}")
    if pending:
        parts.append("\n## Existing Proposals Awaiting Approval")
        parts += [f"- #{p['id']}：{p['action']} → {(p.get('target') or {}).get('display', '')}" for p in pending]
    parts.append(f"\n## Current Message from {owner_name}")
    parts.append(message if message or not attachments else "(Attachments only; no message text.)")
    if guard_notes:
        parts.append("(System notes: " + "; ".join(guard_notes) + ")")
    if attachments:
        parts.append("\n## Attachments for This Turn")
        for i, item in enumerate(attachments, 1):
            header = f"### Attachment {i}: {item['name']} ({KIND_LABEL.get(item['kind'], item['kind'])})"
            parts.append(header + (f"\n{item['extracted']}" if item.get("extracted") else ""))
    return instructions, "\n".join(parts)


def question_criteria(knowledge: str) -> dict[int, dict]:
    out: dict[int, dict] = {}
    blocks = re.split(r"(?m)^\*\*(?:第 |Question )(\d+)(?: 題　| — )", knowledge)
    for i in range(1, len(blocks) - 1, 2):
        number, body = int(blocks[i]), blocks[i + 1]
        title = body.split("**", 1)[0].strip()
        use = re.search(r"- (?:(?:負責人|工程|負責人)?拿(?:答案|來)?要?做什麼：|Purpose:)(.*)", body)
        block = re.search(r"- (?:答完整的標準：|Completeness:)(.*?)(?=\n\*\*(?:第 |Question )|\n## |\Z)", body, re.S)
        criteria: list[str] = []
        if block:
            items = re.findall(r"(?m)^\s+\d+\.\s+(.*)$", block.group(1))
            criteria = [x.strip() for x in items] if items else \
                [x.strip(" 。") for x in re.split(r"[；;]", block.group(1).strip()) if x.strip(" 。")]
        out[number] = {"title": title, "use": use.group(1).strip() if use else "", "criteria": criteria}
    return out
