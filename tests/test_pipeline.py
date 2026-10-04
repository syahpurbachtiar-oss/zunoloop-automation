import unittest
from unittest.mock import patch
from datetime import date, datetime, timezone

from zunoloop.pipeline import next_slot, plan
from zunoloop.buffer import organization_for_channels


class PlanTests(unittest.TestCase):
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
