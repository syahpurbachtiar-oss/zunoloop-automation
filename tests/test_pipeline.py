import unittest
from unittest.mock import patch
from datetime import date, datetime, timezone, timedelta
from email.utils import format_datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo
import json
import os

from zunoloop.pipeline import next_slot, plan, prepare
from zunoloop.buffer import organization_for_channels
from zunoloop.agnes import create_story


class PlanTests(unittest.TestCase):
    def test_story_normalizes_voice_length_and_hashtag_count(self):
        raw = {"title": "belanda vs serbia fans", "caption": "Original illustration inspired by belanda vs serbia. #sport #fans #stadium #match #football",
               "voice": " ".join(["Watch"] + ["fans"] * 24),
               "visual_prompt": "Original football fans in an illuminated stadium."}
        response = {"choices": [{"message": {"content": json.dumps(raw)}}]}
        with patch("zunoloop.agnes.request_json", return_value=response) as send:
            story = create_story("belanda vs serbia", "en")
        self.assertEqual(send.call_count, 1)
        self.assertLessEqual(len(story["voice"].split()), 22)
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
    @patch("zunoloop.pipeline.trends")
    def test_two_localized_trend_sources_and_youtube_slots(self, trends, story):
        trends.side_effect = [[{"title": "topik 1"}, {"title": "topik 2"}],
                              [{"title": "topic 1"}, {"title": "topic 2"}]]
        entries = plan(datetime(2026, 10, 4, 2, 0, tzinfo=timezone.utc))
        self.assertEqual([e["trend"]["title"] for e in entries],
                         ["topik 1", "topik 2", "topic 1", "topic 2"])
        self.assertEqual([e["dueAt"] for e in entries],
                         ["2026-10-04T05:00:00Z", "2026-10-04T13:00:00Z",
                          "2026-10-04T23:00:00Z", "2026-10-05T01:00:00Z"])


if __name__ == "__main__":
    unittest.main()
