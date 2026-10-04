# ZunoLoop: Agnes Video to Buffer

Daily at 09:00 WIB, GitHub Actions reads Google Trends RSS for Indonesia and the US, chooses two topics from the previous 24 hours per market, writes original localized scripts with Agnes text, generates four vertical 12-second videos using Agnes Video 2.5 Flash, and adds exact spoken narration and captions. The two Indonesian videos are shared to both Instagram and TikTok at 12:00 and 20:00 WIB. The two English videos go to YouTube at 06:00 and 08:00 WIB the next day. Buffer receives six scheduled posts. Missed slots move to the next day.

## Current status

**Live posting is paused** with repository variable `LIVE_PUBLISH=false`. Earlier generic test videos are in Buffer Drafts. The Agnes API has not been tested with a real key; the repository has no `AGNES_API_KEY` secret yet. Do not describe this as fully operational until a complete Agnes run succeeds and six queue entries are verified.

The workflow fails closed. Missing/old trends, Agnes errors, malformed scripts, missing or non-vertical media, and insufficient downloads stop the run. There is no generic template fallback. Google Trends measures search interest, not proof that a video will be viral or that a news claim is true. The script avoids making unverified event claims or copying footage. The voice is local `espeak-ng`, which sounds synthetic. ChatGPT Plus does not run inside GitHub Actions and does not provide Agnes API credits.

## Setup and verification

1. Get an API key from [Agnes Platform](https://platform.agnes-ai.com/) and add it as GitHub Actions **secret** `AGNES_API_KEY` in this repository. Do not put it in a public file, issue, or chat message.
2. Keep `LIVE_PUBLISH=false` and manually run the daily workflow. Inspect four MP4 artifacts and `manifest.json` for trend source, time, language, visual quality, and spoken text. The model's free promotion and quota can change; check the Agnes console.
3. Only after a successful live generation, set `LIVE_PUBLISH=true`. The publishing job deploys public MP4s to GitHub Pages, validates their URLs, and schedules six Buffer posts. Verify all six queue entries and their times. `BUFFER_API_KEY` and three channel IDs are already configured; Buffer keys expire and may require rotation.

The repository is public and the published videos will be public. Files under `site/media` are retained for seven days. GitHub scheduled jobs can run late; Agnes, Pages, or Buffer may be delayed or reject a request. Check workflow failures and the Buffer queue rather than assuming a scheduled job published. No system can guarantee followers, views, or affiliate income.

Local check: `python -m unittest discover -s tests`. A full local run requires `AGNES_API_KEY`, FFmpeg, espeak-ng, fonts, and `python -m pip install -r requirements.txt`.

References: [Agnes API integration](https://github.com/AgnesAI-Labs/skills/blob/main/agnes-ai-models/SKILL.md), [model details](https://github.com/AgnesAI-Labs/skills/blob/main/agnes-ai-models/references/model_catalog.md), [Buffer video](https://developers.buffer.com/examples/create-video-post.html), [Buffer scheduling](https://developers.buffer.com/guides/posts-and-scheduling.html).
