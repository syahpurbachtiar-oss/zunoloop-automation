"""Research, script, render, host, and schedule two videos per channel per day."""
import json
import os
import argparse
from datetime import datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from .buffer import create_video_post, organization_for_channels, slot_has_post
from .agnes import create_story, generate_video
from .render import finish_video


EXCLUDE = ("gempa", "bencana", "banjir", "kecelakaan", "meninggal",
           "war", "attack", "shooting", "death", "election", "politik")


def trends(geo):
    """Treat Trends as a topic signal, never as evidence of a factual claim."""
    req = Request(f"https://trends.google.com/trending/rss?geo={geo}",
                  headers={"User-Agent": "ZunoLoopResearch/1.0"})
    try:
        with urlopen(req, timeout=15) as response:
            root = ElementTree.fromstring(response.read(500_000))
        now = datetime.now(timezone.utc)
        results = []
        for item in root.findall("./channel/item"):
            title = item.findtext("title", "").strip()
            published = item.findtext("pubDate", "").strip()
            if not title or not published or any(term in title.casefold() for term in EXCLUDE):
                continue
            try:
                age = now - parsedate_to_datetime(published).astimezone(timezone.utc)
            except (TypeError, ValueError):
                continue
            if timedelta(0) <= age <= timedelta(hours=24):
                results.append({"title": title, "publishedAt": published,
                                "source": item.findtext("link", "").strip() or
                                          f"https://trends.google.com/trending?geo={geo}"})
        unique = {item["title"].casefold(): item for item in reversed(results)}
        if len(unique) < 2:
            raise RuntimeError(f"Fewer than two suitable trends in the past 24h for {geo}")
        return list(unique.values())[:2]
    except (OSError, ElementTree.ParseError) as exc:
        raise RuntimeError(f"Cannot fetch fresh Google Trends for {geo}") from exc


def next_slot(now, zone, hour, minute):
    local = now.astimezone(ZoneInfo(zone))
    candidate = datetime.combine(local.date(), time(hour, minute), ZoneInfo(zone))
    if candidate <= local + timedelta(hours=2):
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def plan(now):
    if not os.getenv("AGNES_API_KEY"):
        raise RuntimeError("AGNES_API_KEY is required; refusing template videos")
    topics_id, topics_en = trends("ID"), trends("US")
    entries = []
    for lang, topics, hours in (
        ("id", topics_id, (12, 20)),
        ("en", topics_en, (6, 8)),
    ):
        for index, topic in enumerate(topics[:2]):
            story = create_story(topic["title"], lang)
            hour = hours[index]
            entries.append({"language": lang, "slot": index + 1,
                            "trend": topic,
                            "story": story,
                            "dueAt": next_slot(now, "Asia/Jakarta", hour, 0)})
    return entries


def prepare():
    now = datetime.now(timezone.utc)
    output = Path("output")
    output.mkdir(exist_ok=True)
    entries = plan(now)
    for entry in entries:
        filename = f"{now.astimezone(ZoneInfo('Asia/Jakarta')).date()}-{entry['language']}-{entry['slot']}.mp4"
        path = output / filename
        raw_path = output / ("raw-" + filename)
        try:
            generate_video(entry["story"]["visual_prompt"], raw_path)
            finish_video(raw_path, entry["story"], entry["language"], path)
        finally:
            raw_path.unlink(missing_ok=True)
        entry["file"] = filename
        entry["generator"] = "agnes-video-2.5-flash"
    (output / "manifest.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2))
    print("Created four Agnes video previews")


def publish():
    if os.getenv("LIVE_PUBLISH", "").lower() != "true":
        raise RuntimeError("LIVE_PUBLISH must be true for scheduling")
    keys = ("BUFFER_API_KEY", "BUFFER_INSTAGRAM_CHANNEL_ID",
            "BUFFER_TIKTOK_CHANNEL_ID", "BUFFER_YOUTUBE_CHANNEL_ID", "MEDIA_BASE_URL")
    missing = [name for name in keys if not os.getenv(name)]
    if missing:
        raise RuntimeError("Missing setup: " + ", ".join(missing))
    base_url = os.environ["MEDIA_BASE_URL"].rstrip("/")
    if not base_url.startswith("https://"):
        raise RuntimeError("MEDIA_BASE_URL must be HTTPS")
    expected = {os.environ["BUFFER_INSTAGRAM_CHANNEL_ID"]: "instagram",
                os.environ["BUFFER_TIKTOK_CHANNEL_ID"]: "tiktok",
                os.environ["BUFFER_YOUTUBE_CHANNEL_ID"]: "youtube"}
    org_id = organization_for_channels(os.environ["BUFFER_API_KEY"], expected)
    entries = json.loads(Path("output/manifest.json").read_text())
    if len(entries) != 4 or sorted(entry.get("language") for entry in entries) != ["en", "en", "id", "id"] or any(
        entry.get("generator") != "agnes-video-2.5-flash"
        or not entry.get("trend", {}).get("publishedAt") for entry in entries
    ):
        raise RuntimeError("Only four source-grounded Agnes videos can be published")
    now = datetime.now(timezone.utc)
    for entry in entries:
        trend_time = parsedate_to_datetime(entry["trend"]["publishedAt"]).astimezone(timezone.utc)
        age = now - trend_time
        due = datetime.fromisoformat(entry["dueAt"].replace("Z", "+00:00"))
        if not timedelta(0) <= age <= timedelta(hours=36) or due <= now + timedelta(minutes=15):
            raise RuntimeError("Trend is stale or scheduled slot is too close; refusing publication")
        filename = entry["file"]
        if Path(filename).name != filename or not filename.endswith(".mp4"):
            raise RuntimeError("Invalid filename in manifest")
        url = base_url + "/media/" + quote(filename)
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
                   if not slot_has_post(os.environ["BUFFER_API_KEY"], org_id,
                                        os.getenv(ch), entry["dueAt"])]
        if not pending:
            continue
        with urlopen(Request(url, headers={"User-Agent": "ZunoLoopPublisher/1.0"}), timeout=30) as response:
            if response.status != 200 or "video/mp4" not in response.headers.get("Content-Type", ""):
                raise RuntimeError("Public media URL is not serving MP4: " + url)
        for channel_id, metadata in pending:
            post = create_video_post(os.environ["BUFFER_API_KEY"], channel_id, url,
                                     entry["story"]["caption"], entry["dueAt"], metadata)
            print(f"Scheduled channel {channel_id}: {post['id']} at {post['dueAt']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true", help="Schedule the prepared videos after public hosting")
    args = parser.parse_args()
    publish() if args.publish else prepare()


if __name__ == "__main__":
    main()
