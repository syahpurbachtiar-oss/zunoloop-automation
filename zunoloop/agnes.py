"""Agnes text/video API. Fail closed on missing credentials or incomplete media."""
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

BASE = "https://apihub.agnes-ai.com"
VIDEO_MODEL = "agnes-video-2.5-flash"


def request_json(path, payload=None):
    key = os.getenv("AGNES_API_KEY")
    if not key:
        raise RuntimeError("AGNES_API_KEY missing")
    video_create = path == "/v1/videos"
    attempts = 15 if video_create else 5
    for retry in range(attempts):
        request = Request(BASE + path,
                          data=json.dumps(payload).encode() if payload is not None else None,
                          headers={"Authorization": "Bearer " + key,
                                   "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=60) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code not in (408, 429, 500, 502, 503, 504, 520, 522, 524) or retry == attempts - 1:
                raise RuntimeError(f"Agnes API HTTP {exc.code} at {path.split('?')[0]}") from exc
            delay = 60 if video_create and exc.code == 503 else min(60, 2 ** retry * 5)
            print(f"Agnes {path.split('?')[0]} HTTP {exc.code}; retrying in {delay}s "
                  f"({retry + 1}/{attempts})", flush=True)
            time.sleep(delay)
    raise RuntimeError("Agnes API retry limit")


def create_story(topic, language):
    language_name = "Bahasa Indonesia" if language == "id" else "English for a US audience"
    prompt = (
        f"Create an original 12-second vertical short in {language_name}, inspired by today's "
        f"Google Trends search phrase {topic!r}. Do not say it is viral, state any news result, "
        "invent facts about real people, reproduce footage, show logos, or imitate protected characters. "
        "Understand what the search phrase actually refers to and keep its category intact. "
        "A sports fixture must be shown through an original sports scene or fans, never "
        "a pun on team names, animals, food, or an invented match result. An athlete's name "
        "must stay in the relevant sport without inventing biography or imitating their face. "
        "Motorsport must be depicted on a safe closed track with protective gear, never "
        "racing on a public road. Avoid national or cultural caricatures. "
        "Use an original illustrative scene that makes the actual topic recognizable, "
        "without claiming it is real footage or making a prediction. "
        "Return ONLY JSON fields title (max 80 characters), caption (max 220 characters "
        "with 2-4 relevant hashtags), voice (max 35 words), visual_prompt (max 900 characters). "
        "The visual_prompt must specify a coherent 9:16 12-second shot with visible motion, "
        "no logos, no text overlays, and characters/objects appropriate for the trend. "
        "Include a hook in voice during the first two seconds. No unverified factual claims. "
        "Invite a comment about the real topic. In the caption make clear the visual is "
        "an original illustration inspired by the search trend, not event footage. "
        f"Include the EXACT search phrase {topic!r} somewhere in title or caption, and "
        "visually connect the scene to that phrase."
    )
    for attempt in range(3):
        reminder = (" Your last answer omitted the exact search phrase from title/caption. "
                    f"This time include {topic!r} verbatim in title or caption."
                    if attempt else "")
        data = request_json("/v1/chat/completions", {"model": "agnes-2.5-flash",
                            "messages": [{"role": "user", "content": prompt + reminder}],
                            "stream": False})
        content = data["choices"][0]["message"]["content"].strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        try:
            story = json.loads(content.strip())
        except json.JSONDecodeError:
            continue
        if any(not isinstance(story.get(field), str) or not 2 < len(story[field]) <= limit
               for field, limit in (("title", 80), ("caption", 220), ("voice", 350),
                                    ("visual_prompt", 900))):
            continue
        if len(story["voice"].split()) > 35 or not 2 <= story["caption"].count("#") <= 4:
            continue
        if " vs " in topic.casefold() and not any(
            word in story["visual_prompt"].casefold()
            for word in ("sport", "match", "game", "pitch", "field", "stadium",
                         "arena", "court", "football", "soccer", "baseball",
                         "pertandingan", "lapangan", "stadion", "sepak bola", "bisbol")
        ):
            continue
        if "motogp" in topic.casefold() and not any(
            word in story["visual_prompt"].casefold()
            for word in ("track", "circuit", "sirkuit", "lintasan")
        ):
            continue
        if topic.casefold() in (story["title"] + " " + story["caption"]).casefold():
            return story
    raise RuntimeError("Agnes did not provide a valid trend-grounded story in three attempts")


def generate_video(visual_prompt, destination):
    model = VIDEO_MODEL
    data = request_json("/v1/videos", {"model": model, "prompt": visual_prompt,
                        "mode": "text", "seconds": "12", "size": "720P",
                        "aspect_ratio": "9:16", "n": 1})
    video_id = data.get("video_id")
    if not video_id:
        raise RuntimeError("Agnes did not return a video_id")
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        time.sleep(15)
        result = request_json("/agnesapi?" + urlencode({"video_id": video_id,
                                                         "model_name": model}))
        status = str(result.get("status", "")).lower()
        if status in ("failed", "error", "cancelled"):
            raise RuntimeError("Agnes video generation failed")
        if status in ("completed", "succeeded", "success", "done"):
            video_url = result.get("url")
            if not isinstance(video_url, str) or urlsplit(video_url).scheme != "https":
                raise RuntimeError("Agnes completion has no HTTPS video URL")
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with urlopen(Request(video_url), timeout=120) as source, destination.open("wb") as out:
                for _ in range(128):
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                else:
                    raise RuntimeError("Agnes video exceeds 128 MiB")
            if destination.stat().st_size < 20_000:
                raise RuntimeError("Agnes video download is incomplete")
            return
    raise TimeoutError("Agnes video was not ready within 15 minutes")
