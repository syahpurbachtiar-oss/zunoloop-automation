# ZunoLoop: Agnes Video to Buffer

Daily at 07:00 WIB, GitHub Actions reads Google Trends RSS for Indonesia and the US, chooses two topics from the previous 24 hours per market, writes original localized scripts with Agnes text, generates four vertical 12-second videos using Agnes Video 2.5 Flash, and adds spoken narration and captions. The two Indonesian videos are shared to both Instagram and TikTok at 12:00 and 20:00 WIB. The two English videos go to YouTube at 06:00 and 08:00 WIB the next day. Buffer receives six scheduled posts after generation succeeds. Missed slots move to the next day.

## Current status

**Live posting is paused** with repository variable `LIVE_PUBLISH=false`. Earlier generic test videos are in Buffer Drafts. The Agnes key is installed as a GitHub Actions secret; three real 12-second generations succeeded in an earlier run, but its fourth request received HTTP 503 (full provider queue). Another preview run is retrying. Do not describe this as fully operational until four current MP4s pass review and six Buffer queue entries are verified.

The workflow fails closed. Missing/old trends, Agnes errors, malformed scripts, missing or non-vertical media, and insufficient downloads stop the run. It retries a busy Agnes queue and saves completed MP4s in the run artifact so a failed run can resume; there is no generic template fallback. Google Trends measures search interest, not proof that a video will be viral or that a news claim is true. The script avoids making unverified event claims or copying footage. The voice is local `espeak-ng`, which sounds synthetic. ChatGPT Plus does not run inside GitHub Actions and does not provide Agnes API credits.

## Setup and verification

1. Keep `LIVE_PUBLISH=false` and inspect a completed daily workflow artifact: four MP4s and `manifest.json` for trend source, time, language, visual quality, and spoken text. The model's free promotion and capacity can change; check the Agnes console.
2. After an incomplete run, dispatch the daily workflow with `resume_run_id` set to that run's ID. It downloads the partial artifact and retains generated MP4s while the manifest remains fresh and the scheduled slots are still ahead.
3. Only after a successful generation, set `LIVE_PUBLISH=true`. For an already generated artifact, dispatch **Publish validated ZunoLoop preview** with its `source_run_id`. The publishing job deploys public MP4s to GitHub Pages, validates their URLs, and schedules six Buffer posts. Verify all six queue entries and their times. `BUFFER_API_KEY`, `AGNES_API_KEY`, and three channel IDs are already configured as secrets or variables; keys may require rotation.

The repository is public and the published videos will be public. Files under `site/media` are retained for seven days. GitHub scheduled jobs can run late; Agnes, Pages, or Buffer may be delayed or reject a request. Check workflow failures and the Buffer queue rather than assuming a scheduled job published. No system can guarantee followers, views, or affiliate income.

Local check: `python -m unittest discover -s tests`. A full local run requires `AGNES_API_KEY`, FFmpeg, espeak-ng, fonts, and `python -m pip install -r requirements.txt`.

References: [Agnes API integration](https://github.com/AgnesAI-Labs/skills/blob/main/agnes-ai-models/SKILL.md), [model details](https://github.com/AgnesAI-Labs/skills/blob/main/agnes-ai-models/references/model_catalog.md), [Buffer video](https://developers.buffer.com/examples/create-video-post.html), [Buffer scheduling](https://developers.buffer.com/guides/posts-and-scheduling.html).
