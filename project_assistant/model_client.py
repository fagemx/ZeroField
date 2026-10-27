"""Shared turn types for the governed built-in transport (providers.py).

The ChatGPT subscription transport was removed (SPEC_20 R3): every model call
goes through an OpenAI-compatible endpoint and ProviderAdmission.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MAX_ROUNDS = 16  # 翻報表一題可能要查十幾次；最後一輪不給工具，只准用查到的回答
LAST_ROUND_NOTE = "（系統附註：查資料的次數到上限了。請用目前查到的內容直接回答；還沒查到的照實說，不要再查。）"


class ModelError(RuntimeError):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind  # quota／auth／unavailable／timeout／bad_response


@dataclass
class TurnResult:
    status: str  # ok／quota／lockdown／error
    answer: str = ""
    blocked: str = ""
    error_kind: str = ""
    error: str = ""
    rounds: int = 0
    usage: dict = field(default_factory=dict)
    seconds: float = 0.0
    first_text: float | None = None
