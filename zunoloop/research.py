"""Fresh public platform coverage. Headlines are inspiration, not verified facts.

This is deliberately NOT a platform ranking API. Missing platform coverage is
reported, allowing the caller to label its search-interest fallback honestly.
"""
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

EXCLUDE = ("gempa", "bencana", "banjir", "kecelakaan", "meninggal", "war",
           "attack", "shooting", "death", "election", "politik", "scam",
           "penipuan", "pembunuhan", "pelecehan", "porn", "bunuh", "suicide",
           "kpu", "pilkada", "pemilu", "partai", "dpr", "president", "presiden",
           "cara mendapatkan uang", "how to make money", "cara menghasilkan uang")


def platform_topics(platform, market, now):
    if platform not in ("instagram", "tiktok", "youtube") or market not in ("ID", "US"):
        raise ValueError("Unsupported research scope")
    query = (f'{platform} (viral OR tren OR trending) Indonesia when:1d' if market == "ID"
             else f'{platform} (trending OR viral) (shorts OR trend) when:1d')
    params = {"q": query, "hl": "id" if market == "ID" else "en-US",
              "gl": market, "ceid": "ID:id" if market == "ID" else "US:en"}
    feed = "https://news.google.com/rss/search?" + urlencode(params)
    try:
        with urlopen(Request(feed, headers={"User-Agent": "ZunoLoopResearch/2.0"}), timeout=20) as response:
            root = ElementTree.fromstring(response.read(1_000_000))
    except (OSError, ElementTree.ParseError) as exc:
        print(f"Platform coverage unavailable for {platform}: {type(exc).__name__}", flush=True)
        return []
    candidates = []
    seen = set()
    for item in root.findall("./channel/item"):
        title = item.findtext("title", "").strip()
        source = item.findtext("link", "").strip()
        published = item.findtext("pubDate", "").strip()
        publisher = item.findtext("source", "").strip()
        # Keep the publisher separately; never confuse a headline with a ranking.
        title = title.rsplit(" - " + publisher, 1)[0] if publisher else title
        if (not title or len(title) > 100 or platform not in title.casefold()
                or not any(word in title.casefold() for word in ("viral", "trending", "tren ", "trend "))
                or not source.startswith("https://")
                or any(word in title.casefold() for word in EXCLUDE)
                or title.casefold() in seen):
            continue
        try:
            age = now - parsedate_to_datetime(published).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        if not timedelta(0) <= age <= timedelta(hours=24):
            continue
        seen.add(title.casefold())
        candidates.append({"title": title, "source": source, "publisher": publisher,
                           "publishedAt": published, "platform": platform, "market": market,
                           "basis": "public_platform_news_coverage",
                           "platformTrendVerified": False, "discoverySource": feed})
    candidates.sort(key=lambda t: parsedate_to_datetime(t["publishedAt"]), reverse=True)
    return candidates[:2]
