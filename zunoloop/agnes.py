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
    for retry in range(5):
        request = Request(BASE + path,
                          data=json.dumps(payload).encode() if payload is not None else None,
                          headers={"Authorization": "Bearer " + key,
                                   "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=60) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code not in (408, 429, 500, 502, 503, 504, 520, 522, 524) or retry == 4:
                raise RuntimeError(f"Agnes API HTTP {exc.code} at {path.split('?')[0]}") from exc
            time.sleep(min(60, 2 ** retry * 5))
    raise RuntimeError("Agnes API retry limit")


def create_story(topic, language):
    language_name = "Bahasa Indonesia" if language == "id" else "English for a US audience"
    prompt = (
        f"Create an original 12-second vertical short in {language_name}, inspired by today's "
        f"Google Trends search phrase {topic!r}. Do not say it is viral, state any news result, "
        "invent facts about real people, reproduce footage, show logos, or imitate protected characters. "
        "Make the trend visibly relevant through a fresh fictional scene. "
        "Return ONLY JSON fields title (max 80 characters), caption (max 220 characters "
        "with 2-4 relevant hashtags), voice (max 35 words), visual_prompt (max 900 characters). "
        "The visual_prompt must specify a coherent 9:16 12-second shot with visible motion, "
        "no logos, no text overlays, and characters/objects appropriate for the trend. "
        "Include a hook in voice during the first two seconds. No unverified factual claims."
    )
    data = request_json("/v1/chat/completions", {"model": "agnes-2.5-flash",
                        "messages": [{"role": "user", "content": prompt}], "stream": False})
    content = data["choices"][0]["message"]["content"].strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    story = json.loads(content.strip())
    for field, limit in (("title", 80), ("caption", 220), ("voice", 350),
                         ("visual_prompt", 900)):
        if not isinstance(story.get(field), str) or not 2 < len(story[field]) <= limit:
            raise RuntimeError(f"Agnes story missing or invalid: {field}")
    if len(story["voice"].split()) > 35 or not 2 <= story["caption"].count("#") <= 4:
        raise RuntimeError("Agnes story failed narration/hashtag validation")
    if topic.casefold() not in (story["title"] + " " + story["caption"] + " " +
                                story["voice"] + " " + story["visual_prompt"]).casefold():
        raise RuntimeError("Story did not mention the trend phrase; no generic fallback")
    return story


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
