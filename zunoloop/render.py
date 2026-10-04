"""Finish and validate original Agnes 9:16 videos."""
import json
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def finish_video(source, story, language, output):
    """Validate Agnes motion, add the exact localized narration and readable text."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe") or not shutil.which("espeak-ng"):
        raise RuntimeError("ffmpeg, ffprobe and espeak-ng are required")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "stream=width,height:format=duration", "-of", "json", str(source)],
                           check=True, capture_output=True, text=True)
    info = json.loads(probe.stdout)
    video_streams = [s for s in info["streams"] if s.get("width") and s.get("height")]
    duration = float(info["format"]["duration"])
    if len(video_streams) != 1 or not 7 <= duration <= 9:
        raise RuntimeError("Agnes did not return one playable 8-second video")
    width, height = video_streams[0]["width"], video_streams[0]["height"]
    if height <= width:
        raise RuntimeError("Agnes returned non-vertical media")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "voice.wav"
        subtitle = Path(tmp) / "subtitle.png"
        subprocess.run(["espeak-ng", "-v", "id" if language == "id" else "en-us",
                        "-s", "185", "-w", str(audio), story["voice"]],
                       check=True, capture_output=True)
        image = Image.new("RGBA", (720, 1280), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((28, 870, 692, 1190), radius=28, fill=(5, 12, 30, 200))
        font = ImageFont.truetype(FONT, 30)
        lines = textwrap.wrap(story["voice"], width=37, break_long_words=False)
        if len(lines) > 7:
            raise RuntimeError("Narration is too long for legible on-screen captions")
        for i, line in enumerate(lines):
            draw.text((52, 895 + 40 * i), line, font=font, fill=(255, 255, 255))
        image.save(subtitle)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source),
                        "-i", str(subtitle), "-i", str(audio),
                        "-filter_complex", "[0:v]scale=720:1280:force_original_aspect_ratio=increase,"
                        "crop=720:1280,setsar=1[v0];[v0][1:v]overlay=0:0[v]",
                        "-map", "[v]", "-map", "2:a", "-af", "apad",
                        "-t", "8", "-r", "24", "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-movflags", "+faststart", str(output)], check=True, capture_output=True)
    if output.stat().st_size < 30_000:
        raise RuntimeError("Finished Agnes video unexpectedly small")
