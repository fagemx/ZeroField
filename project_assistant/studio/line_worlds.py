"""Procedural two-link IK poses and line-worlds structure media."""
from __future__ import annotations

from pathlib import Path
import math
import subprocess
import tempfile

from . import _compat as legacy

__all__ = [
    'solve_ik',
    '_compute_rig_pose',
    '_draw_pose_on_canvas',
    'render_lineworlds_media',
]


def solve_ik(a, b, len1: float = 80.0, len2: float | None = None, side: int = 1) -> tuple[float, float]:
    """2-link inverse kinematics solver ported from line-worlds/art-api.mjs."""
    l1 = float(len1)
    l2 = float(len1 if len2 is None else len2)
    sgn = 1.0 if side >= 0 else -1.0
    dx, dy = float(b[0]) - float(a[0]), float(b[1]) - float(a[1])
    d = max(1e-3, min(math.hypot(dx, dy), (l1 + l2) * 0.998))
    cos_a = max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2.0 * l1 * d)))
    h = l1 * math.sqrt(max(0.0, 1.0 - cos_a * cos_a))
    along = l1 * cos_a
    ux, uy = dx / d, dy / d
    nx, ny = -uy * sgn, ux * sgn
    return (float(a[0]) + ux * along + nx * h, float(a[1]) + uy * along + ny * h)


def _compute_rig_pose(t: float, width: int, height: int, controls: dict, centroid: tuple[float, float] | None = None) -> dict:
    stride = float(controls.get("stride", 0.45))
    turn = float(controls.get("turn", 0.30))
    reach = float(controls.get("reach", 0.50))
    flare = float(controls.get("flare", 0.55))
    zoom = float(controls.get("camera_zoom", 1.0))
    scale = min(width / 600.0, height / 600.0) * max(0.5, min(2.0, zoom))
    if centroid is not None:
        cx, cy = centroid[0] * width, centroid[1] * height
    else:
        cx = width * (0.36 + (0.28 * t) + 0.06 * turn * math.sin(t * math.pi))
        cy = height * (0.56 - 0.04 * math.Abs(math.sin(t * math.pi * 2.0)) if hasattr(math, "Abs") else 0.56 - 0.04 * abs(math.sin(t * math.pi * 2.0)))
    phase_angle = t * math.pi * 2.0
    lean = 0.18 * turn + 0.12 * math.sin(phase_angle)
    sh_center = (cx + lean * 24.0 * scale, cy - 68.0 * scale)
    sh_l = (sh_center[0] - 20.0 * scale, sh_center[1] + 2.0 * scale)
    sh_r = (sh_center[0] + 20.0 * scale, sh_center[1] - 2.0 * scale)
    hip_center = (cx, cy + 26.0 * scale)
    hip_l = (cx - 13.0 * scale, cy + 28.0 * scale)
    hip_r = (cx + 13.0 * scale, cy + 28.0 * scale)
    swing = math.sin(phase_angle)
    hand_l = (sh_l[0] - (36.0 + reach * 28.0) * scale - swing * 18.0 * scale,
              sh_l[1] + (18.0 - reach * 34.0) * scale)
    hand_r = (sh_r[0] + (38.0 + reach * 34.0) * scale + swing * 22.0 * scale,
              sh_r[1] - (12.0 + reach * 38.0) * scale)
    foot_l = (hip_l[0] - stride * 42.0 * scale * math.cos(phase_angle * 0.5),
              hip_l[1] + 92.0 * scale - max(0.0, -swing) * 14.0 * scale)
    foot_r = (hip_r[0] + stride * 42.0 * scale * math.cos(phase_angle * 0.5),
              hip_r[1] + 92.0 * scale - max(0.0, swing) * 14.0 * scale)
    arm_len = 52.0 * scale
    leg_len = 58.0 * scale
    elbow_l = solve_ik(sh_l, hand_l, arm_len, arm_len * 0.95, -1)
    elbow_r = solve_ik(sh_r, hand_r, arm_len, arm_len * 0.95, 1)
    knee_l = solve_ik(hip_l, foot_l, leg_len, leg_len * 0.96, -1)
    knee_r = solve_ik(hip_r, foot_r, leg_len, leg_len * 0.96, 1)
    head = (sh_center[0] + turn * 8.0 * scale, sh_center[1] - 26.0 * scale)
    hem_span = (34.0 + flare * 38.0) * scale
    hem_y = (knee_l[1] + knee_r[1]) * 0.5 + 10.0 * scale
    robe = [
        sh_l,
        (hip_l[0] - 14.0 * scale, hip_l[1] - 12.0 * scale),
        (cx - hem_span * 0.55, hem_y),
        (cx, hem_y + 12.0 * scale),
        (cx + hem_span * 0.55, hem_y),
        (hip_r[0] + 14.0 * scale, hip_r[1] - 12.0 * scale),
        sh_r,
    ]
    return {
        "scale": scale,
        "head": head,
        "sh_center": sh_center,
        "sh_l": sh_l,
        "sh_r": sh_r,
        "elbow_l": elbow_l,
        "elbow_r": elbow_r,
        "hand_l": hand_l,
        "hand_r": hand_r,
        "hip_center": hip_center,
        "hip_l": hip_l,
        "hip_r": hip_r,
        "knee_l": knee_l,
        "knee_r": knee_r,
        "foot_l": foot_l,
        "foot_r": foot_r,
        "robe": robe,
    }


def _draw_pose_on_canvas(draw, pose: dict, *, fill_robe, fill_limb, stroke, hatch: bool = False):
    s = max(1.0, pose["scale"])
    lw = max(1, int(round(2.0 * s)))
    for a, b in ((pose["hip_l"], pose["knee_l"]), (pose["knee_l"], pose["foot_l"]),
                 (pose["hip_r"], pose["knee_r"]), (pose["knee_r"], pose["foot_r"]),
                 (pose["sh_l"], pose["elbow_l"]), (pose["elbow_l"], pose["hand_l"]),
                 (pose["sh_r"], pose["elbow_r"]), (pose["elbow_r"], pose["hand_r"])):
        draw.line([a, b], fill=fill_limb, width=max(2, int(round(7.0 * s))))
        draw.line([a, b], fill=stroke, width=lw)
    if fill_robe:
        draw.polygon(pose["robe"], fill=fill_robe, outline=stroke)
    else:
        draw.polygon(pose["robe"], outline=stroke)
    if hatch:
        xs = [p[0] for p in pose["robe"]]
        ys = [p[1] for p in pose["robe"]]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        step = max(4, int(round(6.0 * s)))
        y = y0 + step
        while y < y1:
            draw.line([(x0 + 4, y), (x1 - 4, y - 3)], fill=stroke, width=1)
            y += step
    r_head = max(4.0, 16.0 * s)
    hx, hy = pose["head"]
    draw.ellipse([hx - r_head, hy - r_head, hx + r_head, hy + r_head], fill=fill_limb or fill_robe, outline=stroke, width=lw)
    for joint in (pose["elbow_l"], pose["elbow_r"], pose["knee_l"], pose["knee_r"], pose["hand_l"], pose["hand_r"]):
        jr = max(2.0, 3.5 * s)
        draw.ellipse([joint[0] - jr, joint[1] - jr, joint[0] + jr, joint[1] + jr], fill=stroke)


def render_lineworlds_media(destination: Path, *, mode: str, width: int, height: int,
                            fps: float = 24.0, frames: int = 25, duration: float = 1.0,
                            controls: dict | None = None, source_video: Path | None = None,
                            has_audio: bool = False, config: dict | None = None) -> dict:
    """Render line-worlds procedural 2-link IK structure media (layout_silhouette, sparse_tracks, time_strata)."""
    from PIL import Image, ImageDraw
    config = config or {}
    controls = dict(controls or {})
    for knob in ("stride", "turn", "reach", "flare", "camera_zoom", "phases"):
        if knob in config and knob not in controls:
            controls[knob] = config[knob]
    centroids = []
    if source_video is not None and source_video.is_file():
        # Sample coarse luma motion centroids across frames (Extract & Re-Rig).
        try:
            raw = subprocess.check_output([
                legacy.ffmpeg_binary(config), "-v", "error", "-i", str(source_video),
                "-vf", "scale=16:16,format=gray", "-frames:v", str(frames),
                "-f", "rawvideo", "-pix_fmt", "gray", "-"
            ], timeout=30)
            frame_bytes = 256
            count = len(raw) // frame_bytes
            for idx in range(count):
                chunk = raw[idx * frame_bytes:(idx + 1) * frame_bytes]
                total_w, wx, wy = 0.0, 0.0, 0.0
                for p_idx, val in enumerate(chunk):
                    px, py = (p_idx % 16) / 15.0, (p_idx // 16) / 15.0
                    weight = abs(float(val) - 128.0) + 1.0
                    total_w += weight
                    wx += px * weight
                    wy += py * weight
                centroids.append((
                    0.28 + 0.44 * (wx / total_w),
                    0.42 + 0.24 * (wy / total_w),
                ))
        except (OSError, subprocess.SubprocessError):
            centroids = []

    if mode == "time_strata":
        img = Image.new("RGB", (width, height), (244, 228, 199))
        draw = ImageDraw.Draw(img)
        horizon_y = int(height * 0.68)
        # Far plane: glowing arch portal & staircase
        arch_x, arch_y = int(width * 0.78), int(height * 0.42)
        arch_w, arch_h = max(24, int(width * 0.11)), max(40, int(height * 0.26))
        draw.rectangle([arch_x - arch_w // 2, arch_y - arch_h // 2, arch_x + arch_w // 2, arch_y + arch_h // 2],
                       fill=(196, 169, 107), outline=(25, 61, 84), width=2)
        for step_idx in range(6):
            sx0 = int(width * 0.18 + step_idx * (width * 0.09))
            sy0 = horizon_y - step_idx * max(4, int(height * 0.03))
            draw.rectangle([sx0, sy0, sx0 + int(width * 0.10), sy0 + max(6, int(height * 0.03))],
                           fill=(102, 139, 156), outline=(25, 61, 84), width=1)
        phases = max(2, min(8, int(controls.get("phases", 5))))
        poses = []
        for idx in range(phases):
            t = idx / float(max(1, phases - 1))
            c_pt = centroids[min(len(centroids) - 1, int(t * len(centroids)))] if centroids else None
            pose = _compute_rig_pose(t, width, height, controls, centroid=c_pt)
            poses.append(pose)
            is_latest = idx == phases - 1
            _draw_pose_on_canvas(
                draw, pose,
                fill_robe=(25, 61, 84) if is_latest else None,
                fill_limb=(102, 139, 156) if is_latest else None,
                stroke=(25, 61, 84),
                hatch=not is_latest,
            )
        # Trajectory ribbons connecting phase anchors (head, right_hand, left_hand)
        for key, col in (("head", (200, 121, 103)), ("hand_r", (25, 61, 84)), ("hand_l", (102, 139, 156))):
            pts = [p[key] for p in poses]
            if len(pts) >= 2:
                draw.line(pts, fill=col, width=2)
        img.save(destination, format="PNG")
        return {"width": width, "height": height, "frames": 1, "mime": "image/png", "role": "time_strata"}

    with tempfile.TemporaryDirectory(prefix="zerofield-lineworlds-") as frame_dir:
        frame_folder = Path(frame_dir)
        history = []
        for idx in range(frames):
            t = idx / float(max(1, frames - 1))
            c_pt = centroids[idx] if idx < len(centroids) else None
            pose = _compute_rig_pose(t, width, height, controls, centroid=c_pt)
            history.append(pose)
            if mode == "sparse_tracks":
                img = Image.new("RGB", (width, height), (8, 10, 16))
                draw = ImageDraw.Draw(img)
                track_specs = (
                    ("head", (6, 182, 212)),
                    ("hand_r", (245, 158, 11)),
                    ("hand_l", (236, 72, 153)),
                    ("hip_center", (16, 185, 129)),
                )
                trail = history[max(0, len(history) - 8):]
                for key, color in track_specs:
                    pts = [p[key] for p in trail]
                    if len(pts) >= 2:
                        draw.line(pts, fill=color, width=max(2, int(round(3.0 * pose["scale"]))))
                    cx, cy = pose[key]
                    r = max(3, int(round(5.5 * pose["scale"])))
                    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color, outline=(255, 255, 255))
            else:
                # layout_silhouette: 3-layer depth blocking (far arch/horizon, mid stairs, near IK silhouette)
                img = Image.new("RGB", (width, height), (22, 27, 36))
                draw = ImageDraw.Draw(img)
                horizon_y = int(height * 0.68)
                draw.rectangle([0, horizon_y, width, height], fill=(42, 51, 66))
                arch_x = int(width * (0.76 - 0.06 * t))
                arch_w, arch_h = max(20, int(width * 0.12)), max(32, int(height * 0.34))
                draw.rectangle([arch_x - arch_w // 2, horizon_y - arch_h, arch_x + arch_w // 2, horizon_y],
                               fill=(72, 88, 110), outline=(148, 163, 184), width=1)
                _draw_pose_on_canvas(
                    draw, pose,
                    fill_robe=(226, 232, 240),
                    fill_limb=(148, 163, 184),
                    stroke=(15, 23, 42),
                    hatch=False,
                )
            img.save(frame_folder / f"frame-{idx:04d}.png", format="PNG")

        args = ["-framerate", str(fps), "-i", str(frame_folder / "frame-%04d.png")]
        if source_video is not None and has_audio:
            args += ["-i", str(source_video), "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "aac"]
        else:
            args += ["-map", "0:v:0"]
        args += [
            "-vf", f"scale={width}:{height},setsar=1,format=yuv420p",
            "-fps_mode", "cfr", "-r", str(fps), "-frames:v", str(frames),
            "-c:v", "libx264", "-preset", config.get("preset", "veryfast"),
            "-pix_fmt", "yuv420p", "-t", str(duration), "-movflags", "+faststart", str(destination)
        ]
        legacy._run_preparation(args, config)
    return {"width": width, "height": height, "frames": frames, "mime": "video/mp4", "role": "motion_structure_video"}
