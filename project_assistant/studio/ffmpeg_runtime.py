"""Shared FFmpeg process lifecycle and video inspection for media and procedural rendering."""
from __future__ import annotations

import json
import math
import subprocess
import tempfile
import time

from . import runtime
from . import _compat as legacy

__all__ = [
    'ffmpeg_binary',
    '_probe_video',
    '_run_preparation',
]


def ffmpeg_binary(config):
    return (config or {}).get("ffmpeg", "ffmpeg")


def _probe_video(path, config=None):
    config = config or {}
    try:
        result = subprocess.run([config.get("ffprobe", "ffprobe"), "-v", "error", "-count_frames", "-show_entries",
            "stream=codec_type,width,height,avg_frame_rate,nb_read_frames,duration:format=duration", "-of", "json", str(path)],
            check=True, capture_output=True, timeout=config.get("probe_timeout", 60))
        metadata = json.loads(result.stdout)
        video = next(s for s in metadata["streams"] if s.get("codec_type") == "video")
        numerator, denominator = video["avg_frame_rate"].split("/")
        fps = float(numerator) / float(denominator)
        duration = float(video.get("duration") or metadata["format"]["duration"])
        frames = int(video["nb_read_frames"])
        if not (math.isfinite(duration) and 0 < duration <= 43200 and math.isfinite(fps) and 0 < fps <= 240 and frames > 0):
            raise ValueError()
        return {"fps": fps, "duration": duration, "frames": frames, "width": int(video["width"]), "height": int(video["height"]),
                "audio": any(s.get("codec_type") == "audio" for s in metadata["streams"])}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration, ZeroDivisionError):
        raise runtime.WorkerError("FFprobe could not inspect source video timing") from None


def _run_preparation(args, config=None):
    config = config or {}
    try:
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen([legacy.ffmpeg_binary(config), "-hide_banner", "-loglevel", "error", "-y", *args],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors)
            deadline = time.monotonic() + config.get("timeout", 1800)
            try:
                while process.poll() is None:
                    if config.get("_lease_lost", lambda: False)():
                        raise runtime.WorkerError("Lease was lost; reference preparation canceled")
                    if time.monotonic() > deadline:
                        raise runtime.WorkerError("FFmpeg reference preparation timed out")
                    time.sleep(.1)
                if process.returncode:
                    raise runtime.WorkerError("FFmpeg could not prepare reference media")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
    except (OSError, subprocess.SubprocessError):
        raise runtime.WorkerError("FFmpeg failed; verify the binary, codecs and input media") from None
