"""Project policy at the boundary to models and remote workers."""
from project_docs import repository as repo
from project_assistant.masking import guard_input


def mode(conn, slug):
    project = repo.get_project(conn, slug)
    if not project:
        raise ValueError("Production not found.")
    return project.get("privacy_mode", "full_access")


def text(conn, slug, value):
    return guard_input(str(value), mask_numbers=mode(conn, slug) == "mask_numbers")


def sanitize(value, privacy_mode):
    """Sanitize values, preserving protocol keys, ids and structural numbers."""
    if isinstance(value, str):
        return guard_input(value, mask_numbers=privacy_mode == "mask_numbers")[0]
    if privacy_mode == "mask_numbers" and isinstance(value, (int, float)) and not isinstance(value, bool):
        cleaned = guard_input(str(value), mask_numbers=True)[0]
        return value if cleaned == str(value) else cleaned
    if isinstance(value, list):
        return [sanitize(v, privacy_mode) for v in value]
    if isinstance(value, dict):
        return {k: sanitize(v, privacy_mode) for k, v in value.items()}
    return value
