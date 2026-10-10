"""Agnes text/video API. Fail closed on missing credentials or incomplete media."""
import json
import hashlib
import os
import re
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
    attempts = 3 if video_create else 5
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


def create_story(topic, language, platform=None, research_basis="google_search_interest"):
    language_name = "Bahasa Indonesia" if language == "id" else "English for a US audience"
    prompt = (
        f"Create an original 8-second vertical short in {language_name}, inspired by today's "
        f"topic signal {topic!r}. Research basis: {research_basis}. Target: {platform or language}. "
        "This signal is inspiration only, not verified platform virality or a verified news fact. "
        "Do not say it is viral, state any news result, "
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
        "with 2-4 relevant hashtags), voice (max 15 Indonesian or 18 English words), visual_prompt (max 900 characters). "
        "The visual_prompt must specify a coherent 9:16 8-second shot with visible motion, "
        "no logos, no text overlays, and characters/objects appropriate for the trend. Never quote lyrics or use existing music.  "
        "Include a hook in voice during the first two seconds. No unverified factual claims. "
        "Invite a comment about the real topic. In the caption make clear the visual is "
        "an original illustration inspired by the topic, not event footage. "
        f"Include the EXACT search phrase {topic!r} somewhere in title or caption, and "
        "visually connect the scene to that phrase."
    )
    prompt += " Use short conversational phrases with expressive punctuation and natural pauses. "
    prompt += "For Indonesian use at most 15 words; for English at most 18 words. Avoid tongue-twisters."
    prompt += " Do not force talking objects; choose people, objects or settings only when relevant. "
    prompt += ("For Instagram prioritize an instantly readable visual reveal. " if platform == "instagram" else
               "For TikTok prioritize a relatable Indonesian situation and quick payoff. " if platform == "tiktok" else
               "For YouTube Shorts use a clear English curiosity hook and visual payoff. ")
    rejection = ""
    for attempt in range(5):
        reminder = (f" Your previous response was rejected: {rejection}. Correct that issue "
                    f"and keep {topic!r} verbatim in title or caption." if attempt else "")
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
            rejection = "Return valid JSON only"
            continue
        if isinstance(story, dict):
            if isinstance(story.get("title"), str) and len(story["title"]) > 80:
                story["title"] = story["title"][:81].rsplit(" ", 1)[0].rstrip(" ,.-:")
            # Agnes often exceeds formatting limits even after a corrective prompt.
            # Keep the hook and normalize only mechanical length/tag constraints.
            if isinstance(story.get("voice"), str):
                words = story["voice"].split()
                if len(words) > (15 if language == "id" else 18):
                    rejection = "Rewrite a complete shorter spoken joke: max 15 Indonesian or 18 English words"
                    continue
            if isinstance(story.get("caption"), str):
                caption = story["caption"]
                tags = list(re.finditer(r"(?<!\w)#[\w]+", caption))
                for match in reversed(tags[4:]):
                    caption = caption[:match.start()] + caption[match.end():]
                if len(tags) < 2:
                    defaults = ("#ZunoLoop", "#Ilustrasi") if language == "id" else ("#ZunoLoop", "#OriginalShort")
                    caption = caption.rstrip() + " " + " ".join(defaults[:2 - len(tags)])
                if len(caption) > 220:
                    tags_text = " ".join(re.findall(r"(?<!\w)#[\w]+", caption)[:4])
                    prefix = "Ilustrasi orisinal" if language == "id" else "Original illustration"
                    caption = f"{prefix}: {topic}. {tags_text}"
                story["caption"] = re.sub(r"\s{2,}", " ", caption).strip()
        if any(not isinstance(story.get(field), str) or not 2 < len(story[field]) <= limit
               for field, limit in (("title", 80), ("caption", 220), ("voice", 350),
                                    ("visual_prompt", 900))):
            rejection = "Invalid field lengths: " + ", ".join(f"{f}={len(story.get(f, '')) if isinstance(story.get(f), str) else 'missing'} (max {limit})" for f,limit in (("title",80),("caption",220),("voice",350),("visual_prompt",900)))
            continue
        if len(story["voice"].split()) > (15 if language == "id" else 18) or not 2 <= story["caption"].count("#") <= 4:
            rejection = "Voice must be at most 22 words and caption must have 2 to 4 hashtags"
            continue
        if " vs " in topic.casefold() and not any(
            word in story["visual_prompt"].casefold()
            for word in ("sport", "match", "game", "pitch", "field", "stadium",
                         "arena", "court", "football", "soccer", "baseball",
                         "fan", "jersey", "player", "ball", "goal", "race",
                         "pertandingan", "lapangan", "stadion", "sepak bola", "bisbol",
                         "penonton", "pemain", "bola", "balap")
        ):
            rejection = "A vs B search is a sports matchup; show a sports scene, not a pun"
            continue
        if "motogp" in topic.casefold() and not any(
            word in story["visual_prompt"].casefold()
            for word in ("track", "circuit", "sirkuit", "lintasan")
        ):
            rejection = "Motogp needs a closed racing track, not a public street"
            continue
        if topic.casefold() in (story["title"] + " " + story["caption"]).casefold():
            return story
        rejection = "The exact search phrase is missing from the title and caption"
    raise RuntimeError(f"Agnes did not provide a valid story for {topic!r}: {rejection}")


def generate_video(visual_prompt, destination):
    model = VIDEO_MODEL
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = destination.with_suffix(".job.json")
    prompt_hash = hashlib.sha256(visual_prompt.encode()).hexdigest()
    if checkpoint.exists():
        data = json.loads(checkpoint.read_text())
        if data.get("prompt_hash") != prompt_hash or data.get("model") != model:
            raise RuntimeError("Agnes checkpoint does not match the requested video")
        video_id = data["video_id"]
        print(f"Resuming existing Agnes job {video_id}", flush=True)
    else:
        data = request_json("/v1/videos", {"model": model, "prompt": visual_prompt,
                            "mode": "text", "seconds": "8", "size": "720P",
                            "aspect_ratio": "9:16", "n": 1})
        video_id = data.get("video_id")
        if not video_id:
            raise RuntimeError("Agnes did not return a video_id")
        checkpoint.write_text(json.dumps({"video_id": video_id, "model": model,
                                         "prompt_hash": prompt_hash}))
        print(f"Agnes accepted video job {video_id}", flush=True)
    previous_status = None
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        time.sleep(15)
        result = request_json("/agnesapi?" + urlencode({"video_id": video_id,
                                                         "model_name": model}))
        status = str(result.get("status", "")).lower()
        if status != previous_status:
            print(f"Agnes job {video_id}: {status}", flush=True)
            previous_status = status
        if status in ("failed", "error", "cancelled"):
            checkpoint.unlink(missing_ok=True)
            raise RuntimeError("Agnes video generation failed")
        if status in ("completed", "succeeded", "success", "done"):
            video_url = result.get("url")
            if not isinstance(video_url, str) or urlsplit(video_url).scheme != "https":
                raise RuntimeError("Agnes completion has no HTTPS video URL")
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = destination.with_suffix(destination.suffix + ".part")
            with urlopen(Request(video_url), timeout=120) as source, partial.open("wb") as out:
                for _ in range(128):
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                else:
                    raise RuntimeError("Agnes video exceeds 128 MiB")
            if partial.stat().st_size < 20_000:
                raise RuntimeError("Agnes video download is incomplete")
            partial.replace(destination)
            checkpoint.unlink(missing_ok=True)
            return
    raise TimeoutError("Agnes video was not ready within 15 minutes")

