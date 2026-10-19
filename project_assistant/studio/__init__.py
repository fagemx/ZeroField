"""Studio API with live legacy exports, including consumed private helpers/state.

Implementations depend only on lower layers; importing Studio never starts a worker.
"""
from importlib import import_module

from . import (_compat, runtime, context_compiler, ffmpeg_runtime, line_worlds,
               media_prep, card_engine, model_router, openapi_v2_hub)

_MODULES = (runtime, context_compiler, ffmpeg_runtime, line_worlds,
            media_prep, card_engine, model_router, openapi_v2_hub)
for _module in _MODULES:
    for _name in _module.__all__:
        _compat.OWNERS[_name] = _module
        _compat.ORIGINALS[_name] = getattr(_module, _name)

# Spec illustrations use these spellings; the original names remain authoritative.
_ALIASES = {"snap_dimensions_32": "snap_dimensions", "build_slot_plan": "slot_plan",
            "render_line_worlds_structure": "render_lineworlds_media",
            "openapi_run_ai_app": "openapi_run_app",
            "trim_video_duration_bounded": "bound_output_video_duration",
            "render_frame_sheet": "build_video_frame_sheet",
            "render_ingredients_sheet": "build_ingredients_sheet"}
_DAEMON = ("llm", "bridge", "speech", "acp_stdio", "ADAPTERS", "process_one", "main")
__all__ = list(_compat.OWNERS) + list(_ALIASES) + list(_DAEMON)


def __getattr__(name):
    if name in _DAEMON:
        return getattr(import_module("project_assistant.limb_worker"), name)
    name = _ALIASES.get(name, name)
    if name not in _compat.OWNERS:
        raise AttributeError(name)
    return getattr(_compat.OWNERS[name], name)


def __dir__():
    return sorted(set(__all__) | set(vars(import_module(__name__))))
