"""Local reference media preparation, bounded video outputs and movie assembly."""
from __future__ import annotations

from pathlib import Path
import io
import json
import math
import mimetypes
import re
import subprocess
import tempfile
import time

from . import context_compiler, line_worlds, runtime
from . import _compat as legacy

__all__ = [
    'bound_output_video_duration',
    'build_video_frame_sheet',
    'build_ingredients_sheet',
    'prepare_reference_media',
    'assemble_files',
    'assemble_side_by_side',
    'ffmpeg',
]


def bound_output_video_duration(raw_video_bytes: bytes, max_duration_sec: float, config: dict | None = None) -> bytes:
    """Trim 17n+5 or 8n+1 upward-padded video outputs back to max_duration_sec as .bounded.mp4."""
    config = config or {}
    limit = float(max_duration_sec)
    if not math.isfinite(limit) or limit <= 0:
        raise runtime.WorkerError("max_duration_sec must be a positive number")
    with tempfile.TemporaryDirectory(prefix="zerofield-bounded-") as folder:
        source = Path(folder) / "render.mp4"
        source.write_bytes(raw_video_bytes)
        media = legacy._probe_video(source, config)
        if media["duration"] <= limit + (0.5 / max(media["fps"], 1.0)):
            return raw_video_bytes
        target_frames = max(1, int(math.floor(limit * media["fps"] + 1e-6)))
        target_duration = target_frames / media["fps"]
        bounded_path = Path(folder) / "render.bounded.mp4"
        legacy._run_preparation([
            "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
            "-r", str(media["fps"]), "-frames:v", str(target_frames), "-t", f"{target_duration:.6f}",
            "-c:v", "libx264", "-crf", "16", "-preset", config.get("preset", "veryfast"),
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(bounded_path)
        ], config)
        bounded = legacy._probe_video(bounded_path, config)
        if (bounded["frames"] != target_frames
                or (bounded["width"], bounded["height"]) != (media["width"], media["height"])
                or bounded["audio"] != media["audio"]):
            raise runtime.WorkerError("Bounded video verification failed")
        return bounded_path.read_bytes()


def build_video_frame_sheet(video_path: Path, duration: float, folder: Path,
                            config: dict | None = None) -> tuple[Path, list[float]]:
    """Extract 8 evenly spaced frames into a 1600x600 timestamped contact sheet for the agent pre-compiler."""
    config = config or {}
    seconds = float(duration)
    if not math.isfinite(seconds) or seconds <= 0:
        raise runtime.WorkerError("Video duration must be positive to build a frame sheet")
    folder = Path(folder)
    fps_expr = f"fps={8.0 / max(seconds, 0.1):.9f},scale=400:280:force_original_aspect_ratio=decrease,pad=400:280:(ow-iw)/2:(oh-ih)/2:white"
    legacy._run_preparation([
        "-i", str(video_path), "-an", "-vf", fps_expr,
        "-frames:v", "8", str(folder / "frame-%02d.png")
    ], config)
    frames = sorted(folder.glob("frame-*.png"))
    if len(frames) < 2:
        raise runtime.WorkerError("Source video did not yield enough frames for an 8-frame contact sheet")
    while len(frames) < 8:
        frames.append(frames[-1])
    times = [round((idx + 0.5) * seconds / 8.0, 3) for idx in range(8)]
    target = folder / "motion_frames.png"
    from PIL import Image, ImageDraw
    sheet = Image.new("RGB", (1600, 600), "white")
    draw = ImageDraw.Draw(sheet)
    for idx, frame_file in enumerate(frames[:8]):
        x, y = (idx % 4) * 400, (idx // 4) * 300
        with Image.open(frame_file) as img:
            sheet.paste(img.convert("RGB"), (x, y + 20))
        draw.text((x + 6, y + 3), f"VIDEO 1 / {times[idx]:.3f}s", fill="black")
    sheet.save(target, format="PNG")
    return target, times


def build_ingredients_sheet(image_blobs: list[bytes], destination: Path,
                            config: dict | None = None) -> tuple[int, int]:
    """Horizontally stitch @Asset reference images into a 32px-aligned LTX-2.5 Ingredients Sheet."""
    config = config or {}
    if not image_blobs:
        raise runtime.WorkerError("Ingredients sheet requires at least one reference image asset")
    from PIL import Image
    images = []
    for raw in image_blobs[:legacy.MAX_MATERIALS]:
        with Image.open(io.BytesIO(raw)) as img:
            images.append(img.convert("RGB"))
    grid_size = int(config.get("grid_size", 32))
    panel_h = int(config.get("height", max(256, max(im.height for im in images))))
    gap = 8
    scaled = []
    for im in images:
        ratio = panel_h / float(max(1, im.height))
        pw = max(64, int(round(im.width * ratio)))
        scaled.append(im.resize((pw, panel_h), Image.Resampling.LANCZOS))
    raw_w = sum(im.width for im in scaled) + gap * max(0, len(scaled) - 1)
    total_w, total_h = context_compiler.snap_dimensions(raw_w, panel_h, grid_size=grid_size)
    canvas = Image.new("RGB", (total_w, total_h), (24, 26, 32))
    content_w = sum(im.width for im in scaled) + gap * max(0, len(scaled) - 1)
    cursor_x = max(0, (total_w - content_w) // 2)
    offset_y = max(0, (total_h - panel_h) // 2)
    for im in scaled:
        if cursor_x + im.width > total_w:
            im = im.resize((max(16, total_w - cursor_x), panel_h), Image.Resampling.LANCZOS)
        canvas.paste(im, (cursor_x, offset_y))
        cursor_x += im.width + gap
    canvas.save(destination, format="PNG")
    return total_w, total_h


def prepare_reference_media(task, config, head, mode):
    ctx = legacy.resolve_studio_context(task)
    local = dict(config, _lease_lost=getattr(head, "lease_lost", lambda: False))
    with tempfile.TemporaryDirectory(prefix="zerofield-reference-") as folder:
        if mode == "ingredients_sheet":
            img_urls = list(ctx.get("asset_images") or [])
            if not img_urls:
                img_urls = [u for u in ([ctx.get("anchor_keyframe"), ctx.get("first_frame")] + context_compiler._shot_media_candidates(task)) if u]
            blobs = []
            for url in dict.fromkeys(img_urls):
                raw, mime = head.asset(task, url)
                if mime.startswith("image/"):
                    blobs.append(raw)
            destination = Path(folder) / "ingredients_sheet.png"
            sheet_w, sheet_h = build_ingredients_sheet(blobs, destination, local)
            if not destination.is_file() or destination.stat().st_size > legacy.MAX_MEDIA:
                raise runtime.WorkerError("Prepared reference is missing or exceeds the 64 MB asset limit")
            asset = head.upload(task, destination.read_bytes(), "image/png", destination.name)
            url = asset["asset_url"]
            identifier = url.rsplit("/", 1)[-1]
            return dict(asset, text=url, content_type="image/png", reference_role="ingredients_sheet",
                        width=sheet_w, height=sheet_h, ltx_ingredients_prompt=ctx.get("ltx_ingredients_prompt", ""),
                        **({"asset_id": identifier} if re.fullmatch(r"pa_[0-9a-f]{32}", identifier) else {}))

        urls = [ctx.get("source_video")] + context_compiler._shot_media_candidates(task)
        source = None
        for url in dict.fromkeys(url for url in urls if url):
            raw, mime = head.asset(task, url)
            if mime.startswith("video/"):
                source = Path(folder) / ("source" + (mimetypes.guess_extension(mime) or ".mp4"))
                source.write_bytes(raw)
                break

        structure = config.get("structure_type", "edge_lineart")
        is_lineworlds = mode == "time_strata" or (mode == "motion_structure" and structure in ("layout_silhouette", "sparse_tracks", "time_strata"))
        if source is None and not is_lineworlds:
            raise runtime.WorkerError("Reference preparation needs a source video asset in the active row")
        metadata = legacy._probe_video(source, config) if source is not None else None
        extra_meta = {}

        if mode == "extract_frame":
            timestamp = float(config.get("timestamp_sec", 0))
            if not math.isfinite(timestamp) or not 0 <= timestamp < metadata["duration"]:
                raise runtime.WorkerError("Reference frame timestamp must fall within the source video")
            destination, mime, role = Path(folder) / "first_frame.png", "image/png", "first_frame"
            vf_args = []
            if config.get("snap_to_grid") or config.get("grid_size"):
                gw, gh = context_compiler.snap_dimensions(int(config.get("width", metadata["width"])),
                                         int(config.get("height", metadata["height"])),
                                         int(config.get("grid_size", 32)))
                vf_args = ["-vf", f"scale={gw}:{gh}:force_original_aspect_ratio=decrease,pad={gw}:{gh}:(ow-iw)/2:(oh-ih)/2"]
            legacy._run_preparation(["-ss", str(timestamp), "-i", str(source), *vf_args, "-frames:v", "1", "-f", "image2", str(destination)], local)
        elif mode == "frame_sheet":
            destination, times = build_video_frame_sheet(source, metadata["duration"], Path(folder), local)
            mime, role = "image/png", "frame_sheet"
            extra_meta["timestamps"] = times
        elif is_lineworlds:
            lw_mode = "time_strata" if mode == "time_strata" or structure == "time_strata" else structure
            grid_size = int(config.get("grid_size", 32 if metadata is None or config.get("snap_to_grid") else 2))
            raw_w = int(config.get("width", metadata["width"] if metadata else 640))
            raw_h = int(config.get("height", metadata["height"] if metadata else 352))
            width, height = context_compiler.snap_dimensions(raw_w, raw_h, grid_size=grid_size) if grid_size > 2 else (raw_w, raw_h)
            if not (16 <= width <= 4096 and 16 <= height <= 4096 and width % 2 == height % 2 == 0):
                raise runtime.WorkerError("Invalid motion structure output size")
            if lw_mode == "time_strata":
                destination, mime, role = Path(folder) / "time_strata.png", "image/png", "time_strata"
                line_worlds.render_lineworlds_media(
                    destination, mode="time_strata", width=width, height=height,
                    controls=config.get("controls"), source_video=source, config=local
                )
            else:
                fps = float(metadata["fps"] if metadata else config.get("fps", 24.0))
                raw_frames = int(metadata["frames"] if metadata else round(float(config.get("duration_sec", 1.0)) * fps))
                frame_rule = config.get("frame_rule", "none" if metadata else "8n+1")
                frames = context_compiler.snap_frame_count(raw_frames, frame_rule)
                duration = metadata["duration"] if (metadata and frames == metadata["frames"]) else (frames / fps)
                destination, mime, role = Path(folder) / "motion_structure.mp4", "video/mp4", "motion_structure_video"
                line_worlds.render_lineworlds_media(
                    destination, mode=lw_mode, width=width, height=height,
                    fps=fps, frames=frames, duration=duration,
                    controls=config.get("controls"), source_video=source,
                    has_audio=bool(metadata and metadata["audio"]), config=local
                )
                rendered = legacy._probe_video(destination, config)
                if rendered["frames"] != frames or not math.isclose(rendered["fps"], fps, rel_tol=0.01):
                    raise runtime.WorkerError("Motion structure timing or audio does not match the source video")
        else:
            width, height = int(config.get("width", metadata["width"])), int(config.get("height", metadata["height"]))
            if config.get("snap_to_grid") or config.get("grid_size"):
                width, height = context_compiler.snap_dimensions(width, height, int(config.get("grid_size", 32)))
            if not (16 <= width <= 4096 and 16 <= height <= 4096 and width % 2 == height % 2 == 0):
                raise runtime.WorkerError("Invalid motion structure output size")
            half_w, half_h = max(16, (width // 4) * 2), max(16, (height // 4) * 2)
            filters = {
                "edge_lineart": "edgedetect=low=0.08:high=0.25,format=yuv420p",
                "luma_depth": "format=gray,eq=contrast=1.35:brightness=0.02,format=yuv420p",
                "frame_diff": "tpad=start=1:start_mode=clone,tblend=all_mode=difference128,setpts=PTS-STARTPTS,format=yuv420p",
                "ref05_edge": f"scale={half_w}:{half_h},gblur=sigma=2.2,edgedetect=low=0.10:high=0.28,scale={width}:{height},format=yuv420p",
                "ref05_depth": f"scale={half_w}:{half_h},gblur=sigma=2.2,format=gray,eq=contrast=1.30:brightness=0.02,scale={width}:{height},format=yuv420p",
            }
            if structure not in filters:
                raise runtime.WorkerError("structure_type must be edge_lineart, luma_depth, frame_diff, ref05_edge, ref05_depth, layout_silhouette, sparse_tracks or time_strata")
            if structure == "frame_diff":
                filters[structure] = filters[structure].replace("setpts=PTS-STARTPTS", f"setpts=N/({metadata['fps']}*TB)")
            cadence = ["-fps_mode", "cfr", "-r", str(metadata["fps"])] if structure == "frame_diff" else ["-fps_mode", "passthrough"]
            vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1," + filters[structure]
            destination, mime, role = Path(folder) / "motion_structure.mp4", "video/mp4", "motion_structure_video"
            legacy._run_preparation(["-i", str(source), "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf, *cadence,
                "-c:v", "libx264", "-preset", config.get("preset", "veryfast"), "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-t", str(metadata["duration"]), "-movflags", "+faststart", str(destination)], local)
            rendered = legacy._probe_video(destination, config)
            if rendered["frames"] != metadata["frames"] or not math.isclose(rendered["fps"], metadata["fps"], rel_tol=0.001) or abs(rendered["duration"] - metadata["duration"]) > 1 / metadata["fps"] + .02 or rendered["audio"] != metadata["audio"]:
                raise runtime.WorkerError("Motion structure timing or audio does not match the source video")
        if not destination.is_file() or destination.stat().st_size > legacy.MAX_MEDIA:
            raise runtime.WorkerError("Prepared reference is missing or exceeds the 64 MB asset limit")
        asset = head.upload(task, destination.read_bytes(), mime, destination.name)
        url = asset["asset_url"]
        identifier = url.rsplit("/", 1)[-1]
        return dict(asset, text=url, content_type=mime, reference_role=role, **extra_meta,
                    **({"asset_id": identifier} if re.fullmatch(r"pa_[0-9a-f]{32}", identifier) else {}))


def assemble_files(clips, destination, config):
    """Normalize videos/stills with optional paired narration; concatenate in row order."""
    binary = config.get("ffmpeg", "ffmpeg")
    width, height, fps = (int(config.get(k, default)) for k, default in (("width", 1280), ("height", 720), ("fps", 24)))
    if not (16 <= width <= 4096 and 16 <= height <= 4096 and width % 2 == height % 2 == 0 and 1 <= fps <= 120):
        raise runtime.WorkerError("Invalid output size or frame rate")
    duration = float(config.get("still_seconds", 4))
    if not 0 < duration <= 600:
        raise runtime.WorkerError("still_seconds must be between 0 and 600")
    timeout = config.get("timeout", 1800)
    def run(args):
        try:
            with tempfile.TemporaryFile() as errors:
                process = subprocess.Popen([binary, "-hide_banner", "-loglevel", "error", "-y", *args],
                                           stdout=subprocess.DEVNULL, stderr=errors, stdin=subprocess.DEVNULL)
                deadline = time.monotonic() + timeout
                try:
                    while process.poll() is None:
                        if config.get("_lease_lost", lambda: False)():
                            raise runtime.WorkerError("Lease was lost; render canceled")
                        if time.monotonic() > deadline:
                            raise runtime.WorkerError("FFmpeg render timed out")
                        time.sleep(.1)
                    if process.returncode:
                        raise runtime.WorkerError("FFmpeg could not process the media inputs")
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
        except (OSError, subprocess.SubprocessError) as exc:
            raise runtime.WorkerError("FFmpeg failed; verify the binary, codecs and input media") from exc
    with tempfile.TemporaryDirectory(prefix="openbench-render-") as folder:
        normalized = []
        for i, clip in enumerate(clips):
            path, mime, audio = clip
            target = Path(folder) / f"clip-{i:04d}.mp4"
            probe = config.get("ffprobe", "ffprobe")
            try:
                check = subprocess.run([probe, "-v", "error", "-show_entries", "stream=codec_type,duration:format=duration", "-of", "json", str(path)],
                                       check=True, capture_output=True, timeout=30)
                metadata = json.loads(check.stdout)
                has_audio = any(s["codec_type"] == "audio" for s in metadata.get("streams", []))
                video_stream = next(s for s in metadata["streams"] if s["codec_type"] == "video")
                clip_seconds = duration if mime.startswith("image/") else float(video_stream.get("duration") or metadata.get("format", {}).get("duration", 0))
                if not 0 < clip_seconds <= 43200:
                    raise ValueError("Invalid video duration")
            except (OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration):
                raise runtime.WorkerError("FFprobe could not inspect the media input and duration") from None
            args = (["-loop", "1"] if mime.startswith("image/") else []) + ["-i", str(path)]
            if audio:
                args += ["-i", str(audio), "-map", "0:v:0", "-map", "1:a:0"]
            else:
                # Normalize with a silent track if input has no audio; retain existing audio.
                if has_audio:
                    args += ["-map", "0:v:0", "-map", "0:a:0"]
                else:
                    args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v:0", "-map", "1:a:0"]
            args += ["-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}",
                     "-c:v", "libx264", "-preset", config.get("preset", "veryfast"), "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-af", "apad", "-shortest"]
            # Explicit duration prevents AAC padding / shortest mux buffering from
            # growing each normalized clip and introducing gaps during concat.
            args += ["-t", str(clip_seconds)]
            run(args + ["-movflags", "+faststart", str(target)])
            normalized.append(target)
        if not normalized:
            raise runtime.WorkerError("Assembly requires at least one video or image asset")
        listing = Path(folder) / "concat.txt"
        listing.write_text("\n".join(f"file '{p.name}'" for p in normalized), encoding="utf-8")
        run(["-f", "concat", "-safe", "1", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(destination)])


def assemble_side_by_side(left_path, right_path, destination, config):
    """Normalize two videos, hstack them, and retain right (else left) audio."""
    width, height, fps = (int(config.get(k, default)) for k, default in (("width", 1280), ("height", 720), ("fps", 24)))
    if not (16 <= width <= 4096 and width % 4 == 0 and 16 <= height <= 4096 and height % 2 == 0 and 1 <= fps <= 120):
        raise runtime.WorkerError("Invalid side-by-side output size or frame rate")
    metadata = [legacy._probe_video(path, config) for path in (left_path, right_path)]
    half = width // 2
    filters = ";".join(f"[{i}:v:0]scale={half}:{height}:force_original_aspect_ratio=decrease,pad={half}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},setpts=PTS-STARTPTS[v{i}]" for i in (0, 1))
    filters += ";[v0][v1]hstack=inputs=2:shortest=1[out]"
    args = ["-i", str(left_path), "-i", str(right_path), "-filter_complex", filters, "-map", "[out]"]
    if any(m["audio"] for m in metadata):
        args += ["-map", "1:a:0" if metadata[1]["audio"] else "0:a:0", "-c:a", "aac", "-af", "apad"]
    args += ["-c:v", "libx264", "-preset", config.get("preset", "veryfast"), "-pix_fmt", "yuv420p", "-t", str(min(m["duration"] for m in metadata)), "-movflags", "+faststart", str(destination)]
    legacy._run_preparation(args, config)


def ffmpeg(task, config, head):
    source = task.get("input", {})
    mode = config.get("mode") or config.get("layout")
    if mode in ("extract_frame", "motion_structure", "frame_sheet", "ingredients_sheet", "time_strata"):
        return prepare_reference_media(task, config, head, mode)
    if mode == "side_by_side":
        row, _ = context_compiler._studio_row(task)
        ctx = legacy.resolve_studio_context(task)
        urls = [url for url in (ctx.get("source_video"), ctx.get("output_video")) if url] + context_compiler._shot_media_candidates(task)
        with tempfile.TemporaryDirectory(prefix="zerofield-compare-") as folder:
            videos = []
            for url in dict.fromkeys(urls):
                data, mime = head.asset(task, url)
                if mime.startswith("video/"):
                    path = Path(folder) / f"input-{len(videos)}{mimetypes.guess_extension(mime) or '.bin'}"
                    path.write_bytes(data)
                    videos.append(path)
                    if len(videos) == 2:
                        break
            if len(videos) != 2:
                raise runtime.WorkerError("Side-by-side comparison requires two video assets")
            destination = Path(folder) / "comparison.mp4"
            legacy.assemble_side_by_side(*videos, destination, dict(config, _lease_lost=getattr(head, "lease_lost", lambda: False)))
            if destination.stat().st_size > legacy.MAX_MEDIA:
                raise runtime.WorkerError("Assembled movie exceeds 64 MB; reduce resolution or duration")
            return head.upload(task, destination.read_bytes(), "video/mp4")
    groups = {}
    # Freeze sheet order first; predecessor outputs override older assets in each row.
    for i, row in enumerate(source.get("rows", [])):
        groups[row.get("row_id") or str(i)] = context_compiler._media_urls(row)
    for result in source.get("predecessor_tasks", []):
        key = result.get("row_id") or result.get("node_id")
        groups.setdefault(key, []).extend(context_compiler._media_urls(result.get("output", {})))
    if not any(groups.values()):
        groups = {}
        for i, url in enumerate(context_compiler._media_urls(source)):
            groups[str(i)] = [url]
    with tempfile.TemporaryDirectory(prefix="openbench-assets-") as folder:
        clips = []
        for index, urls in enumerate(groups.values()):
            candidates, audio = [], None
            for j, url in enumerate(dict.fromkeys(urls)):
                data, mime = head.asset(task, url)
                path = Path(folder) / f"asset-{index}-{j}{mimetypes.guess_extension(mime) or '.bin'}"
                path.write_bytes(data)
                if mime.startswith(("video/", "image/")):
                    candidates.append((path, mime))
                elif mime.startswith("audio/"):
                    audio = path
            if candidates:
                visual = next((c for c in reversed(candidates) if c[1].startswith("video/")), candidates[-1])
                clips.append((*visual, audio))
        destination = Path(folder) / "movie.mp4"
        legacy.assemble_files(clips, destination, dict(config, _lease_lost=getattr(head, "lease_lost", lambda: False)))
        if destination.stat().st_size > legacy.MAX_MEDIA:
            raise runtime.WorkerError("Assembled movie exceeds 64 MB; reduce resolution or duration")
        return head.upload(task, destination.read_bytes(), "video/mp4")
