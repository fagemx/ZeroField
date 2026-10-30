"""Chained Layout Render: start a slice on the previous slice's last frame and guide it toward planned keyframes.

A long one-take is rendered as 8 s Layout Render slices that share their boundary frames. Three optional row images
turn a plain Layout Render into a chained one:

- ``chain_in_frame`` (column "Chain In Frame"): the previous slice's last frame. It is pinned in place as frame 0
  (``LTXVImgToVideoInplace`` on the empty latent, strength 1.0), so the slice continues the take without a seam.
- ``mid_keyframe`` ("Mid Key"): a still the slice should pass through, guided at an inner frame (a multiple of 8,
  strength 0.8), e.g. a small Klein edit of an approved frame that keeps a character's face while the camera moves.
- ``end_keyframe`` ("End Key"): the planned last frame (``LTXVAddGuide`` at frame -1, strength 0.9), which the next
  slice then starts from.

The guides chain after the graph's last guide node and feed the sampler's conditioning, the audio/video concat and
the guide crop, as the LTX keyframe examples do. Each piece is added only when its image is present, so a row without
these cells renders exactly as before.
"""
from __future__ import annotations

SOURCES = ("chain_in_frame", "mid_keyframe", "end_keyframe")

# Node layout of workflows/ltx25_layout_render.json: the empty latent the previs guide (40) is applied to, the last
# guide (42, the pose skeleton), and the nodes that consume its conditioning and latent.
DEFAULTS = {
    "latent": ["21", 0],
    "pin_into": ["40", "latent"],
    "guide_after": "42",
    "vae": ["5", 0],
    "conditioning_users": ["53", "17"],
    "latent_users": [["15", "video_latent"]],
    "frames_node": "20",
    "pin_strength": 1.0,
    "mid_strength": 0.8,
    "end_strength": 0.9,
}


def _next_ids(workflow: dict, count: int) -> list[str]:
    numeric = [int(k) for k in workflow if str(k).isdigit()]
    start = max(numeric, default=0) + 1
    return [str(start + i) for i in range(count)]


def _size(workflow: dict, latent: list) -> tuple[int, int]:
    inputs = workflow.get(str(latent[0]), {}).get("inputs", {})
    return int(inputs.get("width", 1280)), int(inputs.get("height", 704))


def mid_frame(workflow: dict, options: dict) -> int:
    """The inner guide frame: options["mid_frame"], else the middle of the previs (rounded down to a multiple of 8)."""
    if options.get("mid_frame") is not None:
        frame = int(options["mid_frame"])
    else:
        cap = workflow.get(str(options["frames_node"]), {}).get("inputs", {}).get("frame_load_cap")
        frame = int(cap) // 2 if isinstance(cap, int) else 96
    return max(8, frame // 8 * 8)


def add_chain_guides(workflow: dict, ctx: dict, options: dict | None = None) -> dict:
    """Add the pin and guides whose images are in ``ctx``; return the bindings for their ``LoadImage`` slots."""
    options = dict(DEFAULTS, **(options or {}))
    present = [name for name in SOURCES if ctx.get(name)]
    if not present:
        return {}
    width, height = _size(workflow, options["latent"])
    bindings = {}

    def load(source):
        loader, scale = _next_ids(workflow, 2)
        workflow[loader] = {"class_type": "LoadImage", "inputs": {"image": f"{source}.png"}}
        workflow[scale] = {"class_type": "ImageScale", "inputs": {"image": [loader, 0], "upscale_method": "lanczos",
                                                                  "width": width, "height": height, "crop": "center"}}
        bindings[f"{loader}.image"] = {"source": source, "upload": "image", "label": source}
        return scale

    if "chain_in_frame" in present:
        scale = load("chain_in_frame")
        (pin,) = _next_ids(workflow, 1)
        workflow[pin] = {"class_type": "LTXVImgToVideoInplace", "inputs": {
            "vae": list(options["vae"]), "image": [scale, 0], "latent": list(options["latent"]),
            "strength": float(options["pin_strength"]), "bypass": False}}
        node, field = options["pin_into"]
        workflow[str(node)]["inputs"][field] = [pin, 0]
    previous = str(options["guide_after"])
    guides = [(name, frame, strength) for name, frame, strength in (
        ("end_keyframe", -1, options["end_strength"]),
        ("mid_keyframe", mid_frame(workflow, options), options["mid_strength"])) if name in present]
    for source, frame, strength in guides:
        scale = load(source)
        (guide,) = _next_ids(workflow, 1)
        workflow[guide] = {"class_type": "LTXVAddGuide", "inputs": {
            "positive": [previous, 0], "negative": [previous, 1], "vae": list(options["vae"]), "latent": [previous, 2],
            "image": [scale, 0], "frame_idx": int(frame), "strength": float(strength)}}
        previous = guide
    if guides:
        for node in options["conditioning_users"]:
            inputs = workflow[str(node)]["inputs"]
            inputs["positive"], inputs["negative"] = [previous, 0], [previous, 1]
        for node, field in options["latent_users"]:
            workflow[str(node)]["inputs"][field] = [previous, 2]
    return bindings
