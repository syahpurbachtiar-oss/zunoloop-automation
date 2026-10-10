import unittest
from unittest.mock import patch
from datetime import date, datetime, timezone, timedelta
from email.utils import format_datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo
import json
import os

from zunoloop.pipeline import next_slot, plan, prepare, publish
from zunoloop.buffer import organization_for_channels
from zunoloop.agnes import create_story


class PlanTests(unittest.TestCase):
    def test_partial_batch_publishes_ready_localized_videos_without_duplicates(self):
        now = datetime.now(timezone.utc)
        entries = [{"language": lang, "slot": i % 2 + 1,
                    "trend": {"publishedAt": format_datetime(now)},
                    "dueAt": (now + timedelta(hours=3+i)).isoformat(),
                    "story": {"caption": "Original illustration #ZunoLoop #Ilustrasi"}}
                   for i, lang in enumerate(("id", "id", "en", "en"))]
        for i in range(2):
            entries[i].update(file=f"ready-{i}.mp4", generator="agnes-video-2.5-flash")
        env = {"LIVE_PUBLISH": "true", "BUFFER_API_KEY": "test",
               "BUFFER_INSTAGRAM_CHANNEL_ID": "ig", "BUFFER_TIKTOK_CHANNEL_ID": "tt",
               "BUFFER_YOUTUBE_CHANNEL_ID": "yt", "MEDIA_BASE_URL": "https://example.com"}
        with patch.dict(os.environ, env), \
             patch("zunoloop.pipeline.Path.read_text", return_value=json.dumps(entries)), \
             patch("zunoloop.pipeline.organization_for_channels", return_value="org"), \
             patch("zunoloop.pipeline.slot_has_post", side_effect=[True, False, False, False]), \
             patch("zunoloop.pipeline.urlopen") as media, \
             patch("zunoloop.pipeline.create_video_post", return_value={"id": "post", "dueAt": "future"}) as create:
            response = media.return_value.__enter__.return_value
            response.status = 200
            response.headers = {"Content-Type": "video/mp4"}
            publish()
        self.assertEqual([call.args[1] for call in create.call_args_list], ["tt", "ig", "tt"])
        self.assertEqual(media.call_count, 2)

    def test_long_story_metadata_is_normalized_without_cutting_narration(self):
        raw = {"title": "Apa Artinya Cinta " + "scene " * 20,
               "caption": "An original illustration " * 20 + "#Music #Mood",
               "voice": "Pernah merasa begini? Ceritakan versimu!",
               "visual_prompt": "An original couple sharing a warm smile in a vertical 9:16 shot."}
        with patch("zunoloop.agnes.request_json", return_value={"choices": [{"message": {"content": json.dumps(raw)}}]}):
            result = create_story("Apa Artinya Cinta", "id", platform="tiktok")
        self.assertLessEqual(len(result["title"]), 80)
        self.assertLessEqual(len(result["caption"]), 220)
        self.assertIn("Apa Artinya Cinta", result["caption"])
        self.assertEqual(result["voice"], raw["voice"])

    def test_story_rewrites_long_narration_without_truncating_joke(self):
        raw = {"title": "belanda vs serbia fans", "caption": "Original illustration inspired by belanda vs serbia. #sport #fans #stadium #match #football",
               "voice": " ".join(["Watch"] + ["fans"] * 24),
               "visual_prompt": "Original football fans in an illuminated stadium."}
        short = dict(raw, voice="Watch these fans cheer before the whistle even blows!")
        responses = [{"choices": [{"message": {"content": json.dumps(item)}}]} for item in (raw, short)]
        with patch("zunoloop.agnes.request_json", side_effect=responses) as send:
            story = create_story("belanda vs serbia", "en")
        self.assertEqual(send.call_count, 2)
        self.assertEqual(story["voice"], short["voice"])
        self.assertLessEqual(len(story["voice"].split()), 18)
        self.assertEqual(story["caption"].count("#"), 4)

    def test_sports_trend_rejects_animal_pun_then_corrects(self):
        bad = {"title": "Cardinals vs Giants", "caption": "Birds and dogs play. #Cardinals #Giants",
               "voice": "Who wins this backyard duel?", "visual_prompt": "Birds and a dog in a backyard."}
        good = {"title": "Cardinals vs Giants fan moment", "caption": "Original fan scene inspired by cardinals vs giants. #football #fans",
                "voice": "Which side are you cheering for today?", "visual_prompt": "Original football fans in red and blue jerseys at a stadium."}
        responses = [{"choices": [{"message": {"content": json.dumps(item)}}]} for item in (bad, good)]
        with patch("zunoloop.agnes.request_json", side_effect=responses) as send:
            self.assertEqual(create_story("cardinals vs giants", "en"), good)
        self.assertIn("sports matchup", send.call_args_list[1].args[1]["messages"][0]["content"])

    def test_resume_reuses_completed_video_and_checkpoints_remaining(self):
        now = datetime.now(timezone.utc)
        entries = []
        for index, lang in enumerate(("id", "id", "en", "en")):
            due = now + timedelta(hours=4 + index)
            entries.append({
                "language": lang, "slot": (index % 2) + 1,
                "trend": {"title": f"topic {index}", "publishedAt": format_datetime(now)},
                "story": {"visual_prompt": f"scene {index}", "voice": "hello"},
                "dueAt": due.isoformat().replace("+00:00", "Z"),
            })
        first = entries[0]
        filename = f"{datetime.fromisoformat(first['dueAt'].replace('Z', '+00:00')).astimezone(ZoneInfo('Asia/Jakarta')).date()}-id-1.mp4"
        first.update({"file": filename, "generator": "agnes-video-2.5-flash"})
        def generate(prompt, path):
            Path(path).write_bytes(b"raw")
        def render(source, story, lang, path):
            Path(path).write_bytes(b"video" * 7000)
        with TemporaryDirectory() as temp:
            old = os.getcwd()
            try:
                os.chdir(temp)
                output = Path("output")
                output.mkdir()
                (output / filename).write_bytes(b"video" * 7000)
                (output / "manifest.json").write_text(json.dumps(entries))
                with patch("zunoloop.pipeline.plan") as fresh, \
                     patch("zunoloop.pipeline.generate_video", side_effect=generate) as video, \
                     patch("zunoloop.pipeline.finish_video", side_effect=render):
                    prepare()
                    fresh.assert_not_called()
                    self.assertEqual(video.call_count, 3)
                saved = json.loads((output / "manifest.json").read_text())
                self.assertEqual(len([item for item in saved if item.get("file")]), 4)
            finally:
                os.chdir(old)

    def test_future_slot_uses_local_zone(self):
        now = datetime(2026, 10, 4, 2, 0, tzinfo=timezone.utc)
        self.assertEqual(next_slot(now, "Asia/Jakarta", 12, 0), "2026-10-04T05:00:00Z")
        self.assertGreater(datetime.fromisoformat(next_slot(now, "America/New_York", 19, 0)
                                                  .replace("Z", "+00:00")), now)

    def test_no_late_slot(self):
        now = datetime(2026, 10, 4, 4, 30, tzinfo=timezone.utc)
        self.assertEqual(next_slot(now, "Asia/Jakarta", 12, 0), "2026-10-05T05:00:00Z")

    @patch("zunoloop.buffer._graphql")
    def test_channel_mapping_must_match_all_three_platforms(self, graphql):
        graphql.side_effect = [
            {"account": {"organizations": [{"id": "org1"}]}},
            {"channels": [{"id": "ig", "service": "instagram"},
                          {"id": "tt", "service": "tiktok"},
                          {"id": "yt", "service": "youtube"}]},
        ]
        self.assertEqual(organization_for_channels("key", {"ig": "instagram", "tt": "tiktok",
                                                            "yt": "youtube"}), "org1")
        graphql.side_effect = [
            {"account": {"organizations": [{"id": "org1"}]}},
            {"channels": [{"id": "ig", "service": "instagram"},
                          {"id": "tt", "service": "tiktok"}]},
        ]
        with self.assertRaises(RuntimeError):
            organization_for_channels("key", {"ig": "instagram", "tt": "tiktok",
                                              "yt": "youtube"})

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_agnes_key_cannot_generate_templates(self):
        with self.assertRaisesRegex(RuntimeError, "AGNES_API_KEY"):
            plan(datetime(2026, 10, 4, 2, 0, tzinfo=timezone.utc))

    @patch.dict("os.environ", {"AGNES_API_KEY": "test"})
    @patch("zunoloop.pipeline.create_story", return_value={"title": "test"})
    @patch("zunoloop.pipeline.platform_topics", side_effect=[[], [], []])
    @patch("zunoloop.pipeline.trends")
    def test_separate_platform_batches_label_fallback(self, trends, coverage, story):
        trends.side_effect = [[{"title": f"topik {i}", "source": "https://example.com"} for i in range(4)],
                              [{"title": f"topic {i}", "source": "https://example.com"} for i in range(2)]]
        entries = plan(datetime(2026, 10, 4, 2, 0, tzinfo=timezone.utc))
        self.assertEqual([e["platform"] for e in entries],
                         ["instagram", "instagram", "tiktok", "tiktok", "youtube", "youtube"])
        self.assertEqual([e["trend"]["title"] for e in entries],
                         ["topik 0", "topik 1", "topik 2", "topik 3", "topic 0", "topic 1"])
        self.assertTrue(all(not e["trend"]["platformTrendVerified"] for e in entries))
        self.assertEqual(coverage.call_count, 3)
        self.assertEqual(story.call_count, 6)
        self.assertEqual([e["dueAt"] for e in entries[-2:]],
                         ["2026-10-04T23:00:00Z", "2026-10-05T01:00:00Z"])

    def test_platform_video_never_crossposts_to_other_indonesian_channel(self):
        from zunoloop.pipeline import valid_batch
        now = datetime.now(timezone.utc)
        entries = []
        for platform in ("instagram", "tiktok", "youtube"):
            for slot in (1, 2):
                entries.append({"platform": platform, "language": "en" if platform == "youtube" else "id",
                                "slot": slot, "trend": {"publishedAt": format_datetime(now)},
                                "dueAt": (now + timedelta(hours=4+slot)).isoformat(),
                                "story": {"title": "Test", "caption": "Illustration"}})
        self.assertTrue(valid_batch(entries))
        entries[0].update(file="ig.mp4", generator="agnes-video-2.5-flash")
        env = {"LIVE_PUBLISH": "true", "BUFFER_API_KEY": "test",
               "BUFFER_INSTAGRAM_CHANNEL_ID": "ig", "BUFFER_TIKTOK_CHANNEL_ID": "tt",
               "BUFFER_YOUTUBE_CHANNEL_ID": "yt", "MEDIA_BASE_URL": "https://example.com"}
        with patch.dict(os.environ, env), \
             patch("zunoloop.pipeline.Path.read_text", return_value=json.dumps(entries)), \
             patch("zunoloop.pipeline.organization_for_channels", return_value="org"), \
             patch("zunoloop.pipeline.slot_has_post", return_value=False), \
             patch("zunoloop.pipeline.urlopen") as media, \
             patch("zunoloop.pipeline.create_video_post", return_value={"id": "post", "dueAt": "future"}) as create:
            media.return_value.__enter__.return_value.status = 200
            media.return_value.__enter__.return_value.headers = {"Content-Type": "video/mp4"}
            publish()
        self.assertEqual([call.args[1] for call in create.call_args_list], ["ig"])
        entries[0]["platform"] = "tiktok"
        self.assertFalse(valid_batch(entries))


if __name__ == "__main__":
    unittest.main()
