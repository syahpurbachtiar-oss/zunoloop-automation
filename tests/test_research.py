import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from xml.sax.saxutils import escape
from zunoloop.research import platform_topics, short_topic


class ResearchTests(unittest.TestCase):
    def test_platform_coverage_excludes_stale_future_and_unrelated_headlines(self):
        now = datetime.now(timezone.utc)
        rows = [('TikTok tren kopi Indonesia', now),
                ('Viral Tsunami 60 Meter Akibat Erupsi Anak Krakatau di TikTok', now),
                ('TikTok tren lama', now-timedelta(hours=25)),
                ('TikTok tren masa depan', now+timedelta(hours=2)),
                ('Instagram tren Indonesia', now)]
        xml = '<rss><channel>' + ''.join(
            f'<item><title>{escape(title)}</title><pubDate>{format_datetime(date)}</pubDate>'
            '<link>https://news.google.com/rss/articles/example</link><source>Publisher</source></item>'
            for title,date in rows) + '</channel></rss>'
        with patch('zunoloop.research.urlopen') as request:
            request.return_value.__enter__.return_value.read.return_value = xml.encode()
            topics = platform_topics('tiktok', 'ID', now)
        self.assertEqual(len(topics), 1)
        self.assertEqual(topics[0]['title'], 'TikTok tren kopi Indonesia')
        self.assertEqual(topics[0]['basis'], 'public_platform_news_coverage')
        self.assertFalse(topics[0]['platformTrendVerified'])
        self.assertEqual(topics[0]['market'], 'ID')

    def test_missing_coverage_is_not_fabricated(self):
        with patch('zunoloop.research.urlopen', side_effect=OSError('unavailable')):
            self.assertEqual(platform_topics('instagram', 'ID', datetime.now(timezone.utc)), [])

class HeadlineTests(unittest.TestCase):
    def test_long_song_article_keeps_meaningful_short_anchor(self):
        self.assertEqual(short_topic("Lirik Lagu Dulug Dug Dag Kicau Mania yang Lagi Viral Terbaru di TikTok: Permisi Kak Kita Lagi Ngamen"), "Dulug Dug Dag Kicau Mania")
        self.assertEqual(short_topic("Lirik Belum Juga kah Kau Menyadarinya Viral di Tiktok, Lagu Apa Artinya Cinta - Melly Goeslaw"), "Apa Artinya Cinta - Melly Goeslaw")
