"""Original 9:16 graphic shorts. No third-party footage or music."""
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


SIZE = (720, 1280)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def frame(message, number, output):
    image = Image.new("RGB", SIZE)
    pixels = image.load()
    for y in range(SIZE[1]):
        for x in range(SIZE[0]):
            pixels[x, y] = (6 + y // 90, 16 + x // 50, 47 + y // 55)
    draw = ImageDraw.Draw(image)
    shift = 35 * number
    draw.ellipse((80 + shift, 130, 640 + shift, 690), fill=(7, 78, 112))
    draw.ellipse((135 + shift, 185, 585 + shift, 635), fill=(0, 161, 187))
    draw.ellipse((205 + shift, 255, 515 + shift, 565), fill=(6, 24, 59))
    draw.rounded_rectangle((42, 745, 678, 1095), radius=36, fill=(7, 13, 39))
    large = ImageFont.truetype(FONT, 51)
    small = ImageFont.truetype(FONT, 28)
    brand = ImageFont.truetype(FONT, 38)
    lines = textwrap.wrap(message, width=20, break_long_words=False)
    if len(lines) > 4:
        lines = textwrap.wrap(message, width=25, break_long_words=False)
        large = ImageFont.truetype(FONT, 39)
    y = 800 + max(0, 3 - len(lines)) * 31
    for line in lines[:5]:
        box = draw.textbbox((0, 0), line, font=large)
        draw.text(((SIZE[0] - (box[2] - box[0])) // 2, y), line,
                  font=large, fill=(252, 253, 255))
        y += 65
    draw.text((45, 48), "ZUNOLOOP", font=brand, fill=(42, 227, 229))
    draw.text((45, 1170), f"{number + 1}/4  |  ORIGINAL SHORT", font=small,
              fill=(255, 179, 100))
    image.save(output)


def render_video(story, language, output):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        pictures = [folder / f"frame-{i}.png" for i in range(4)]
        for i, message in enumerate(story["frames"]):
            frame(message, i, pictures[i])
        audio = folder / "voice.wav"
        if shutil.which("espeak-ng"):
            subprocess.run(["espeak-ng", "-v", "id" if language == "id" else "en-us",
                            "-s", "165", "-w", str(audio), story["voice"]],
                           check=True, capture_output=True)
        else:
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "anullsrc=r=44100:cl=mono", "-t", "12", "-y", str(audio)],
                           check=True, capture_output=True)
        args = ["ffmpeg", "-v", "error", "-y"]
        for picture in pictures:
            args.extend(["-loop", "1", "-t", "3", "-i", str(picture)])
        args.extend(["-i", str(audio), "-filter_complex",
                     "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0[v]",
                     "-map", "[v]", "-map", "4:a", "-af", "apad",
                     "-t", "12", "-r", "24", "-c:v", "libx264", "-preset", "veryfast",
                     "-crf", "26", "-pix_fmt", "yuv420p", "-c:a", "aac",
                     "-movflags", "+faststart", str(output)])
        subprocess.run(args, check=True, capture_output=True)
    if output.stat().st_size < 10_000:
        raise RuntimeError("Rendered video is unexpectedly small")
