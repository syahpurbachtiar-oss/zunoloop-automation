import unittest
from unittest.mock import patch
from datetime import date, datetime, timezone

from zunoloop.pipeline import choose_objects, next_slot, plan
from zunoloop.buffer import organization_for_channels


class PlanTests(unittest.TestCase):
    def test_trend_match_ranks_object_first(self):
        objects = choose_objects(date(2026, 10, 4), ["Spons lucu viral", "gempa hari ini"])
        self.assertEqual(objects[0], ("spons", "sponge"))

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

    @patch("zunoloop.pipeline.trends")
    def test_indonesia_and_us_choose_their_own_topics(self, trends):
        trends.side_effect = [["Spons lucu viral"], ["Umbrella hack"]]
        entries = plan(datetime(2026, 10, 4, 2, 0, tzinfo=timezone.utc))
        self.assertEqual([e["object"] for e in entries if e["language"] == "id"][0], "spons")
        self.assertEqual([e["object"] for e in entries if e["language"] == "en"][0], "umbrella")


if __name__ == "__main__":
    unittest.main()
