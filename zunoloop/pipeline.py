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
from .render import finish_video, PROFILE
from .research import platform_topics


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
        return list(unique.values())[:8]
    except (OSError, ElementTree.ParseError) as exc:
        raise RuntimeError(f"Cannot fetch fresh Google Trends for {geo}") from exc


def next_slot(now, zone, hour, minute):
    local = now.astimezone(ZoneInfo(zone))
    candidate = datetime.combine(local.date(), time(hour, minute), ZoneInfo(zone))
    if candidate <= local + timedelta(hours=2):
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def trend_age(trend, now):
    # Reviewed batches expire 24h after research, independently of news publication.
    if trend.get("researchedAt"):
        observed = datetime.fromisoformat(trend["researchedAt"].replace("Z", "+00:00"))
        age = now - observed.astimezone(timezone.utc)
        if not timedelta(0) <= age <= timedelta(hours=24):
            raise RuntimeError("Reviewed research is stale")
        return age
    return now - parsedate_to_datetime(trend["publishedAt"]).astimezone(timezone.utc)


def valid_batch(entries):
    if len(entries) == 4 and all("platform" not in e for e in entries):
        return sorted(e.get("language", "") for e in entries) == ["en", "en", "id", "id"]
    expected = {(p, i) for p in ("instagram", "tiktok", "youtube") for i in (1, 2)}
    return (len(entries) == 6 and {(e.get("platform"), e.get("slot")) for e in entries} == expected
            and all(e.get("language") == ("en" if e.get("platform") == "youtube" else "id")
                    for e in entries))


def plan(now):
    if not os.getenv("AGNES_API_KEY"):
        raise RuntimeError("AGNES_API_KEY is required; refusing template videos")
    reviewed = os.getenv("REVIEWED_PLAN", "")
    if reviewed:
        path = Path(reviewed)
        if path.parent != Path("plans") or path.suffix != ".json":
            raise RuntimeError("Reviewed plan must be a plans/*.json file")
        entries = json.loads(path.read_text())
        if not valid_batch(entries):
            raise RuntimeError("Invalid reviewed batch")
        for entry in entries:
            trend_age(entry["trend"], now)
            due = datetime.fromisoformat(entry["dueAt"].replace("Z", "+00:00"))
            if due <= now + timedelta(minutes=15):
                raise RuntimeError("Reviewed slot has passed")
        return entries
    entries = []
    regional = {}
    for platform, lang, geo, hours in (
        ("instagram", "id", "ID", (12, 20)),
        ("tiktok", "id", "ID", (12, 20)),
        ("youtube", "en", "US", (6, 8)),
    ):
        # Independent platform coverage first; general search interest is an
        # explicitly labelled fallback, never a claim of platform virality.
        topics = platform_topics(platform, geo, now)
        if len(topics) < 2:
            if geo not in regional:
                regional[geo] = trends(geo)
            fallback = regional[geo]
            if platform == "tiktok":
                fallback = fallback[2:] + fallback[:2]
            used = {t["title"].casefold() for t in topics}
            for topic in fallback:
                if topic["title"].casefold() not in used:
                    topics.append(dict(topic, platform=platform, market=geo,
                                       basis="google_search_interest",
                                       platformTrendVerified=False))
                    used.add(topic["title"].casefold())
                if len(topics) == 2:
                    break
        if len(topics) < 2:
            raise RuntimeError(f"Insufficient fresh research for {platform}")
        for index, topic in enumerate(topics[:2]):
            print(f"Research {platform}: {topic['title']} [{topic['basis']}] {topic['source']}", flush=True)
            story = create_story(topic["title"], lang, platform=platform,
                                 research_basis=topic["basis"])
            entries.append({"platform": platform, "language": lang, "slot": index + 1,
                            "trend": topic, "story": story,
                            "dueAt": next_slot(now, "Asia/Jakarta", hours[index], 0)})
    return entries


def prepare():
    now = datetime.now(timezone.utc)
    output = Path("output")
    output.mkdir(exist_ok=True)
    manifest = output / "manifest.json"
    if manifest.exists():
        entries = json.loads(manifest.read_text())
        if not valid_batch(entries):
            raise RuntimeError("Invalid resume manifest")
        for entry in entries:
            age = trend_age(entry["trend"], now)
            due = datetime.fromisoformat(entry["dueAt"].replace("Z", "+00:00"))
            ready = (entry.get("generator") == "agnes-video-2.5-flash"
                     and entry.get("file") and (output / entry["file"]).is_file())
            if not timedelta(0) <= age <= timedelta(hours=36) or (not ready and due <= now + timedelta(minutes=15)):
                raise RuntimeError("Resume manifest is stale; fresh research required")
    else:
        entries = plan(now)
        manifest.write_text(json.dumps(entries, ensure_ascii=False, indent=2))
    for entry in entries:
        filename = f"{datetime.fromisoformat(entry['dueAt'].replace('Z', '+00:00')).astimezone(ZoneInfo('Asia/Jakarta')).date()}-{entry.get('platform', entry['language'])}-{entry['slot']}.mp4"
        path = output / filename
        if (entry.get("file") == filename and entry.get("generator") == "agnes-video-2.5-flash"
                and path.is_file() and path.stat().st_size > 30_000):
            print(f"Reusing verified prior Agnes file {filename}", flush=True)
            continue
        raw_path = output / "sources" / ("raw-" + filename)
        raw_path.parent.mkdir(exist_ok=True)
        if not raw_path.exists():
            generate_video(entry["story"]["visual_prompt"], raw_path)
        finish_video(raw_path, entry["story"], entry["language"], path)
        entry["renderProfile"] = PROFILE
        entry["file"] = filename
        entry["generator"] = "agnes-video-2.5-flash"
        manifest.write_text(json.dumps(entries, ensure_ascii=False, indent=2))
    print(f"Created {len(entries)} Agnes video previews")


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
    if not valid_batch(entries):
        raise RuntimeError("Invalid source-grounded batch")
    ready = [entry for entry in entries if entry.get("file")
             and entry.get("generator") == "agnes-video-2.5-flash"
             and entry.get("trend", {}).get("publishedAt")]
    if not ready:
        raise RuntimeError("No completed Agnes videos available for publication")
    print(f"Publishing {len(ready)} completed Agnes videos; {len(entries) - len(ready)} still pending", flush=True)
    now = datetime.now(timezone.utc)
    for entry in ready:
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
        if entry.get("platform"):
            channel_specs = [(ch, meta) for ch, meta in channel_specs
                             if entry["platform"] in meta]
            if len(channel_specs) != 1:
                raise RuntimeError("Invalid platform routing")
        pending = [(os.getenv(ch), meta) for ch, meta in channel_specs
                   if not slot_has_post(os.environ["BUFFER_API_KEY"], org_id,
                                        os.getenv(ch), entry["dueAt"])]
        if not pending:
            continue
        age = trend_age(entry["trend"], now)
        due = datetime.fromisoformat(entry["dueAt"].replace("Z", "+00:00"))
        if not timedelta(0) <= age <= timedelta(hours=36) or due <= now + timedelta(minutes=15):
            raise RuntimeError("Trend is stale or scheduled slot is too close; refusing publication")
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

