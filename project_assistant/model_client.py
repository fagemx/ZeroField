"""Shared turn types for the governed built-in transport (providers.py).

The ChatGPT subscription transport was removed (SPEC_20 R3): every model call
goes through an OpenAI-compatible endpoint and ProviderAdmission.

Failure classes (SPEC_20 R12) are what people see: local (the local model server is
down or broken), quota, auth, provider (a hosted service or the request setup failed),
timeout, empty (no answer and no tool calls) and output (the answer was malformed or
looped on tools), plus gpu_busy (the local GPU stayed busy with a render, SPEC_20 R13).
`error_kind` keeps the transport detail for logs and tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MAX_ROUNDS = 16  # 翻報表一題可能要查十幾次；最後一輪不給工具，只准用查到的回答
LAST_ROUND_NOTE = "（系統附註：查資料的次數到上限了。請用目前查到的內容直接回答；還沒查到的照實說，不要再查。）"
FAILURE_CLASSES = ('local', 'quota', 'auth', 'provider', 'timeout', 'empty', 'output', 'gpu_busy')
# Plain-language fallbacks for surfaces without the UI dictionary (the UI uses providerFailures.*).
FAILURE_TEXT = {
    'local': "The local model isn't answering. Start Ollama (or the local model server) on the studio computer, then try again.",
    'quota': 'The model service is out of quota or rate-limiting this studio. Wait a little and try again.',
    'auth': 'The model service rejected the API key. The showrunner can check the key in Agent Console.',
    'provider': "The model service had a problem and didn't finish. Try again; if it keeps happening, the showrunner can check Agent Console.",
    'timeout': 'The model took too long to answer. Try again, or ask for something smaller.',
    'empty': 'The model sent back an empty answer. Try again, or rephrase the request.',
    'output': "The model's answer couldn't be used (it was malformed or kept calling tools). Try again, or rephrase the request.",
    'gpu_busy': 'The GPU is busy with a render, so the local model could not start. Try again shortly.',
}


def failure_class(kind: str, *, local: bool = False) -> str:
    """Map a transport error kind to the class people see."""
    if kind in FAILURE_CLASSES and kind != 'local':
        return kind
    if kind in ('unavailable', 'bad_response'):
        return 'local' if local else 'provider'  # the server itself was down or answered garbage
    return 'provider'  # configuration, kind_removed, refused inputs and anything unforeseen


class ModelError(RuntimeError):
    def __init__(self, kind: str, message: str, failure: str | None = None):
        super().__init__(message)
        self.kind = kind  # quota／auth／unavailable／timeout／bad_response／bad_request／empty／output／gpu_busy
        self.failure = failure  # overrides failure_class(kind) when the evidence is more specific


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
    failure: str = ""     # one of FAILURE_CLASSES when status is error or quota
    model: str = ""       # the model the provider reported answering with, if it said
    trimmed: dict = field(default_factory=dict)  # context-budget trimming (SPEC_20 R10); empty when nothing was cut
