import io
import json
import hashlib
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from zunoloop.recovery import choose
from zunoloop.agnes import generate_video


class RecoveryTests(unittest.TestCase):
    def saved_batch(self, complete=False, batch_date="2026-10-10"):
        archive = io.BytesIO()
        entries = [{"batchDate": batch_date, "file": "ready.mp4", "generator": "agnes-video-2.5-flash"}
                   for _ in range(4)]
        if not complete:
            entries[-1] = {"batchDate": batch_date}
        with ZipFile(archive, "w") as z:
            z.writestr("manifest.json", json.dumps(entries))
            z.writestr("ready.mp4", b"v" * 31000)
        return archive.getvalue()

    def run_info(self, conclusion="failure"):
        return {"workflow_runs": [{"id": 123, "created_at": "2026-10-10T07:00:00Z",
                                   "status": "completed", "conclusion": conclusion}]}

    def test_scheduled_retry_resumes_partial_batch(self):
        with patch("zunoloop.recovery.api", side_effect=[self.run_info(),
                   {"artifacts": [{"id": 8, "name": "zunoloop-123", "expired": False}]},
                   self.saved_batch()]):
            result = choose(datetime(2026, 10, 10, 9, tzinfo=timezone.utc), "schedule", "7,37 * * * *")
        self.assertEqual(result, {"resume": "123", "skip": False, "publish_ready": False})

    def test_completed_successful_batch_is_not_generated_again(self):
        with patch("zunoloop.recovery.api", side_effect=[self.run_info("success"),
                   {"artifacts": [{"id": 8, "name": "zunoloop-123", "expired": False}]},
                   self.saved_batch(complete=True)]):
            self.assertTrue(choose(datetime(2026, 10, 10, 9, tzinfo=timezone.utc),
                                   "schedule", "7,37 * * * *")["skip"])

    def test_failure_event_resumes_saved_batch_instead_of_new_research(self):
        with patch("zunoloop.recovery.api", side_effect=[self.run_info(),
                   {"artifacts": [{"id": 8, "name": "zunoloop-123", "expired": False}]},
                   self.saved_batch()]):
            result = choose(datetime(2026, 10, 10, 9, tzinfo=timezone.utc), "workflow_run", "")
        self.assertEqual(result, {"resume": "123", "skip": False, "publish_ready": False})

    def test_failure_event_without_checkpoint_does_not_start_new_batch(self):
        with patch("zunoloop.recovery.api", return_value={"workflow_runs": []}):
            self.assertTrue(choose(datetime(2026, 10, 10, 9, tzinfo=timezone.utc),
                                   "workflow_run", "")["skip"])

    def test_recovery_resumes_newest_recovery_artifact_not_unrelated_run(self):
        runs = self.run_info()
        runs["workflow_runs"][0]["name"] = "ZunoLoop recover saved videos"
        runs["workflow_runs"].insert(0, {"name": "Verify Buffer video batch"})
        with patch("zunoloop.recovery.api", side_effect=[runs,
                   {"artifacts": [{"id": 8, "name": "zunoloop-123", "expired": False}]},
                   self.saved_batch()]):
            result = choose(datetime(2026, 10, 10, 9, tzinfo=timezone.utc), "workflow_run", "")
        self.assertEqual(result["resume"], "123")

    def test_daily_start_does_not_resume_yesterdays_batch_from_today_recovery(self):
        with patch("zunoloop.recovery.api", side_effect=[self.run_info(),
                   {"artifacts": [{"id": 8, "name": "zunoloop-123", "expired": False}]},
                   self.saved_batch(batch_date="2026-10-09")]):
            result = choose(datetime(2026, 10, 10, 9, tzinfo=timezone.utc), "schedule", "0 5 * * *")
        self.assertEqual(result, {"resume": "", "skip": False, "publish_ready": False})

    def test_retry_does_not_create_new_batch_when_no_checkpoint_exists(self):
        with patch("zunoloop.recovery.api", return_value={"workflow_runs": []}):
            self.assertTrue(choose(datetime(2026, 10, 10, 9, tzinfo=timezone.utc),
                                   "schedule", "7,37 * * * *")["skip"])

    def test_existing_agnes_job_is_polled_without_another_submission(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "video.mp4"
            checkpoint = path.with_suffix(".job.json")
            checkpoint.write_text(json.dumps({"video_id": "existing", "model": "agnes-video-2.5-flash",
                                              "prompt_hash": hashlib.sha256(b"scene").hexdigest()}))
            with patch("zunoloop.agnes.request_json", return_value={"status": "completed", "url": "https://example.com/video.mp4"}) as request, \
                 patch("zunoloop.agnes.time.sleep"), \
                 patch("zunoloop.agnes.time.monotonic", side_effect=[0, 1]), \
                 patch("zunoloop.agnes.urlopen", return_value=io.BytesIO(b"v" * 31000)):
                generate_video("scene", path)
            self.assertEqual(request.call_count, 1)
            self.assertTrue(request.call_args.args[0].startswith("/agnesapi?"))
            self.assertEqual(path.stat().st_size, 31000)
            self.assertFalse(checkpoint.exists())
