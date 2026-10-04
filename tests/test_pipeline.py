import unittest
from datetime import date, datetime, timezone

from zunoloop.pipeline import choose_objects, next_slot


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


if __name__ == "__main__":
    unittest.main()
