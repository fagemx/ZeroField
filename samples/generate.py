"""Reproduce the original CC0 procedural playback fixtures (Pillow + FFmpeg).
These are stylized test animations, not FLUX/LTX model renders.
"""
from pathlib import Path
import math
import random
import subprocess
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
SIZE = (640, 360)


def scene(close=False, courier=False):
    image = Image.new("RGB", SIZE)
    draw = ImageDraw.Draw(image)
    for y in range(360):
        draw.line((0, y, 640, y), fill=(9 + y // 35, 20 + y // 24, 29 + y // 18))
    draw.ellipse((65, -160, 590, 355), outline=(67, 103, 111), width=6)
    for x in range(110, 600, 95):
        draw.line((320, -30, x, 310), fill=(40, 67, 77), width=3)
    draw.rectangle((0, 282, 640, 360), fill=(12, 22, 29))
    draw.polygon([(0, 360), (190, 285), (490, 285), (640, 360)], fill=(24, 38, 44))
    draw.ellipse((350, 85, 360, 95), fill=(176, 213, 201))
    rng = random.Random(48291)
    for _ in range(70):
        x, y = rng.randrange(80, 580), rng.randrange(0, 275)
        draw.line((x, y, x - 3, y + 8), fill=(65, 88, 101), width=1)
    draw.rounded_rectangle((420, 240, 575, 303), 7, fill=(25, 35, 39), outline=(96, 110, 102), width=2)
    for x in range(435, 570, 18):
        draw.rectangle((x, 260, x + 6, 268), fill=(203, 137, 64))
    if courier:
        draw.ellipse((226, 107, 282, 171), fill=(23, 25, 29), outline=(99, 117, 118), width=2)
        draw.polygon([(225, 166), (280, 166), (309, 285), (200, 285)], fill=(37, 44, 49))
        draw.line((251, 177, 252, 275), fill=(91, 104, 103), width=3)
        draw.polygon([(222, 282), (245, 282), (240, 350), (215, 350)], fill=(17, 23, 28))
        draw.polygon([(260, 282), (284, 282), (299, 350), (274, 350)], fill=(17, 23, 28))
        draw.rounded_rectangle((270, 207, 309, 241), 3, fill=(31, 34, 32), outline=(186, 139, 76), width=2)
    if close:
        draw.rounded_rectangle((156, 85, 490, 300), 16, fill=(28, 34, 36), outline=(103, 120, 116), width=3)
        for x in (250, 390):
            draw.ellipse((x - 42, 110, x + 42, 194), fill=(12, 20, 24), outline=(164, 146, 104), width=4)
            draw.ellipse((x - 8, 144, x + 8, 160), fill=(93, 116, 111))
        draw.rounded_rectangle((190, 212, 452, 256), 5, fill=(14, 27, 28), outline=(90, 130, 115))
        for x in range(200, 445):
            y = 235 + int(math.sin(x / 8) * 10 * math.sin(x / 35))
            draw.point((x, y), fill=(119, 200, 157))
        draw.ellipse((447, 104, 459, 116), fill=(227, 157, 75))
    return image


def movie(still, destination, warm=False):
    filters = "zoompan=z='min(zoom+0.0007,1.07)':d=72:s=640x360:fps=24"
    if warm:
        filters += ",colorbalance=rs=0.08:bs=-0.05,eq=saturation=0.82"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1",
        "-i", str(still), "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000",
        "-t", "3", "-vf", filters, "-af", "volume=0.025", "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "25", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(destination)], check=True)


def main():
    scene(courier=True).save(ROOT / "cast_kael.png")
    scene().save(ROOT / "set_observatory.png")
    scene(courier=True).save(ROOT / "keyframe_s01.png")
    scene(close=True).save(ROOT / "keyframe_s02.png")
    movie(ROOT / "keyframe_s01.png", ROOT / "shot_s01.mp4")
    movie(ROOT / "keyframe_s02.png", ROOT / "shot_s02.mp4")
    movie(ROOT / "keyframe_s01.png", ROOT / "openjutsu_source.mp4")
    movie(ROOT / "keyframe_s01.png", ROOT / "openjutsu_remastered.mp4", warm=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(ROOT / "openjutsu_source.mp4"), "-frames:v", "1", str(ROOT / "first_frame_vfx01.png")], check=True)
    scene(courier=True).save(ROOT / "anchor_keyframe_vfx01.png")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(ROOT / "openjutsu_source.mp4"), "-vf", "edgedetect=low=0.08:high=0.25,format=yuv420p",
        "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "23", "-c:a", "copy", "-movflags", "+faststart", str(ROOT / "motion_structure_vfx01.mp4")], check=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(ROOT / "openjutsu_source.mp4"), "-i", str(ROOT / "openjutsu_remastered.mp4"),
        "-filter_complex", "[0:v][1:v]hstack=inputs=2[v]", "-map", "[v]", "-map", "1:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "25", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-movflags", "+faststart", str(ROOT / "openjutsu_split.mp4")], check=True)


if __name__ == "__main__":
    main()
