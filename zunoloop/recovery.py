"""Choose the latest saved batch; scheduled recovery never creates a second batch."""
import io
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile
from zoneinfo import ZoneInfo


def api(path, binary=False):
    req = Request("https://api.github.com/repos/" + os.environ["GITHUB_REPOSITORY"] + path,
                  headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                           "Accept": "application/vnd.github+json"})
    with urlopen(req, timeout=60) as response:
        if binary:
            data = response.read(256 * 1024 * 1024 + 1)
            if len(data) > 256 * 1024 * 1024:
                raise RuntimeError("Saved batch exceeds recovery download limit")
            return data
        return json.load(response)


def choose(now, event, schedule, requested="", publish_ready=False):
    if event not in ("schedule", "workflow_run"):
        if requested and not requested.isdigit():
            raise RuntimeError("Invalid recovery run ID")
        return {"resume": requested, "skip": False, "publish_ready": publish_ready}
    fresh_start = event == "schedule" and schedule == "0 5 * * *"
    today = now.astimezone(ZoneInfo("Asia/Jakarta")).date()
    runs = api("/actions/workflows/daily.yml/runs?per_page=30")["workflow_runs"]
    for run in runs:
        created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        if now - created > timedelta(hours=36):
            break
        if run["status"] != "completed":
            continue
        if fresh_start and created.astimezone(ZoneInfo("Asia/Jakarta")).date() != today:
            break
        artifacts = api(f"/actions/runs/{run['id']}/artifacts")["artifacts"]
        matching = [a for a in artifacts if a["name"] == f"zunoloop-{run['id']}" and not a["expired"]]
        if not matching:
            continue
        with ZipFile(io.BytesIO(api(f"/actions/artifacts/{matching[0]['id']}/zip", binary=True))) as archive:
            info = archive.getinfo("manifest.json")
            if info.file_size > 2 * 1024 * 1024:
                raise RuntimeError("Oversized saved manifest")
            entries = json.loads(archive.read(info))
            if not isinstance(entries, list) or len(entries) not in (4, 6):
                raise RuntimeError("Invalid saved production batch")
            batch_date = next((e.get("batchDate") or e.get("file", "")[:10]
                               for e in entries if e.get("batchDate") or e.get("file")),
                              created.astimezone(ZoneInfo("Asia/Jakarta")).date().isoformat())
            if fresh_start and batch_date != today.isoformat():
                break
            ready = all(e.get("generator") == "agnes-video-2.5-flash"
                        and e.get("file") in archive.namelist()
                        and archive.getinfo(e["file"]).file_size > 30_000 for e in entries)
        if ready and run["conclusion"] == "success":
            return {"resume": "", "skip": True, "publish_ready": False}
        return {"resume": str(run["id"]), "skip": False, "publish_ready": ready}
    return {"resume": "", "skip": not fresh_start, "publish_ready": False}


def main():
    result = choose(datetime.now(timezone.utc), os.environ.get("EVENT_NAME", ""),
                    os.environ.get("EVENT_SCHEDULE", ""), os.environ.get("INPUT_RESUME", ""),
                    os.environ.get("INPUT_PUBLISH", "").lower() == "true")
    print("Recovery selection:", json.dumps(result), flush=True)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as out:
        for key, value in result.items():
            out.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")


if __name__ == "__main__":
    main()
