"""Research, script, render, host, and schedule two videos per channel per day."""
import json
import os
import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from .buffer import create_video_post, slot_has_post
from .cloudinary import upload_video
from .render import render_video


OBJECTS = [
    ("payung", "umbrella"), ("tas sekolah", "backpack"),
    ("sikat gigi", "toothbrush"), ("sepatu", "sneakers"),
    ("jam weker", "alarm clock"), ("botol minum", "water bottle"),
    ("bantal", "pillow"), ("spons", "sponge"),
    ("kacamata", "glasses"), ("pintu", "door"),
]
EXCLUDE = ("gempa", "bencana", "banjir", "kecelakaan", "meninggal",
           "war", "attack", "shooting", "death", "election", "politik")


def trends(geo):
    """Treat Trends as a topic signal, never as evidence of a factual claim."""
    req = Request(f"https://trends.google.com/trending/rss?geo={geo}",
                  headers={"User-Agent": "ZunoLoopResearch/1.0"})
    try:
        with urlopen(req, timeout=15) as response:
            root = ElementTree.fromstring(response.read(500_000))
        return [n.text.strip() for n in root.findall("./channel/item/title") if n.text]
    except (OSError, ElementTree.ParseError):
        return []


def choose_objects(day, trend_titles):
    normalized = [x.casefold() for x in trend_titles
                  if not any(bad in x.casefold() for bad in EXCLUDE)]
    favored = [obj for obj in OBJECTS
               if any(obj[0] in t or obj[1] in t for t in normalized)]
    rotated = OBJECTS[day.toordinal() % len(OBJECTS):] + OBJECTS[:day.toordinal() % len(OBJECTS)]
    return (favored + [x for x in rotated if x not in favored])[:2]


def default_story(obj, language, slot):
    id_name, en_name = obj
    if language == "id":
        hook = f"Kalau {id_name} bisa bicara..."
        lines = [hook, f"'Aku selalu siap bantu kamu,' kata {id_name}.",
                 "Tapi giliran dicari, aku selalu hilang!", "Benda apa lagi yang harus bicara?"]
        return {"title": f"{id_name.title()} Punya Keluhan!",
                "frames": lines,
                "voice": " ".join(lines),
                "caption": f"{id_name.title()} akhirnya curhat! Benda apa lagi? #ZunoLoop #BendaBicara #VideoLucu"}
    lines = [f"If a {en_name} could talk...", f"'I help you every day,' says the {en_name}.",
             "And then you lose me right on cue!", "Which object should speak next?"]
    return {"title": f"The {en_name.title()} Has a Complaint!",
            "frames": lines, "voice": " ".join(lines),
            "caption": f"What if your {en_name} talked back? #ZunoLoop #TalkingObjects #Shorts"}


def ai_story(obj, language, trend_titles, slot):
    """Optional OpenAI-compatible text API. Falls back to original local script."""
    fallback = default_story(obj, language, slot)
    key, url = os.getenv("CONTENT_API_KEY"), os.getenv("CONTENT_API_URL")
    if not key or not url:
        return fallback
    if not url.startswith("https://"):
        raise ValueError("CONTENT_API_URL must be HTTPS")
    prompt = (
        f"Write an original 12-second talking-object short in language {language}. "
        f"Object: {obj[0] if language == 'id' else obj[1]}. "
        f"Slot: {slot}. Today search topics for context only: {trend_titles[:8]}. "
        "Avoid claims about news/events, named people, fear, disasters, copyright, "
        "products and affiliate promises. No borrowed viral footage. "
        "Return JSON only: title (<=90 chars), frames (exactly 4 short strings), "
        "voice (<=30 words), caption (<=220 chars, 2-4 hashtags)."
    )
    body = json.dumps({"model": os.getenv("CONTENT_MODEL", ""),
                       "messages": [{"role": "user", "content": prompt}],
                       "response_format": {"type": "json_object"}}).encode()
    try:
        req = Request(url, body, headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"})
        with urlopen(req, timeout=40) as response:
            result = json.load(response)
        text = result["choices"][0]["message"]["content"]
        story = json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip()).strip())
        if (not isinstance(story.get("frames"), list) or len(story["frames"]) != 4
                or any(not isinstance(s, str) or len(s) > 110 for s in story["frames"])):
            return fallback
        for field, limit in (("title", 90), ("voice", 320), ("caption", 220)):
            if not isinstance(story.get(field), str) or not 0 < len(story[field]) <= limit:
                return fallback
        if len(story["voice"].split()) > 30:
            return fallback
        combined = " ".join([story["title"], story["voice"], story["caption"],
                             *story["frames"]]).casefold()
        if any(bad in combined for bad in EXCLUDE):
            return fallback
        return story
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return fallback


def next_slot(now, zone, hour, minute):
    local = now.astimezone(ZoneInfo(zone))
    candidate = datetime.combine(local.date(), time(hour, minute), ZoneInfo(zone))
    if candidate <= local + timedelta(hours=2):
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def plan(now):
    local_day = now.astimezone(ZoneInfo("Asia/Jakarta")).date()
    topics_id, topics_en = trends("ID"), trends("US")
    chosen = choose_objects(local_day, topics_id + topics_en)
    entries = []
    for index, obj in enumerate(chosen):
        for lang in ("id", "en"):
            story = ai_story(obj, lang, topics_id if lang == "id" else topics_en, index + 1)
            zone = "Asia/Jakarta" if lang == "id" else "America/New_York"
            hour = (12, 20)[index] if lang == "id" else (19, 21)[index]
            entries.append({"language": lang, "slot": index + 1,
                            "object": obj[0] if lang == "id" else obj[1],
                            "story": story,
                            "dueAt": next_slot(now, zone, hour, 0),
                            "trendMatched": any(obj[0] in s.casefold() or obj[1] in s.casefold()
                                                for s in (topics_id if lang == "id" else topics_en))})
    return entries


def main():
    now = datetime.now(timezone.utc)
    output = Path("output")
    output.mkdir(exist_ok=True)
    entries = plan(now)
    live = os.getenv("LIVE_PUBLISH", "").lower() == "true"
    if live:
        keys = ("BUFFER_API_KEY", "BUFFER_ORGANIZATION_ID", "BUFFER_INSTAGRAM_CHANNEL_ID",
                "BUFFER_TIKTOK_CHANNEL_ID", "BUFFER_YOUTUBE_CHANNEL_ID",
                "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET")
        missing = [name for name in keys if not os.getenv(name)]
        if missing:
            raise RuntimeError("Missing setup: " + ", ".join(missing))
    for entry in entries:
        filename = f"{now.astimezone(ZoneInfo('Asia/Jakarta')).date()}-{entry['language']}-{entry['slot']}.mp4"
        path = output / filename
        render_video(entry["story"], entry["language"], path)
        if not live:
            continue
        channel_specs = ([
            ("BUFFER_INSTAGRAM_CHANNEL_ID", {"instagram": {"type": "reel", "shouldShareToFeed": True,
                                                           "isAiGenerated": True}}),
            ("BUFFER_TIKTOK_CHANNEL_ID", {"tiktok": {"isAiGenerated": True}}),
        ] if entry["language"] == "id" else [
            ("BUFFER_YOUTUBE_CHANNEL_ID", {"youtube": {"title": entry["story"]["title"],
                                                           "categoryId": "24", "isAiGenerated": True,
                                                           "madeForKids": False}}),
        ])
        pending = [(os.getenv(ch), meta) for ch, meta in channel_specs
                   if not slot_has_post(os.environ["BUFFER_API_KEY"], os.environ["BUFFER_ORGANIZATION_ID"],
                                        os.getenv(ch), entry["dueAt"])]
        if not pending:
            continue
        url = upload_video(path, os.environ["CLOUDINARY_CLOUD_NAME"],
                           os.environ["CLOUDINARY_API_KEY"], os.environ["CLOUDINARY_API_SECRET"])
        for channel_id, metadata in pending:
            post = create_video_post(os.environ["BUFFER_API_KEY"], channel_id, url,
                                     entry["story"]["caption"], entry["dueAt"], metadata)
            print(f"Scheduled channel {channel_id}: {post['id']} at {post['dueAt']}")
    (output / "manifest.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2))
    print("Created four language-specific videos; live scheduling=" + str(live))


if __name__ == "__main__":
    main()
