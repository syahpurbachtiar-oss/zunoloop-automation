# ZunoLoop daily video pipeline

Generates **two Indonesian videos** for Instagram Reels and TikTok and **two English videos** for YouTube Shorts each day. Runs in GitHub Actions at 09:00 WIB. Buffer receives explicit channel times: Instagram/TikTok at 12:00 and 20:00 WIB; YouTube at 19:00 and 21:00 America/New_York (DST aware). A run that starts too late moves a slot to the next day.

## Current scope

- Reads Google Trends RSS for ID and US as a **topic signal**. It only uses matches from a safe list of talking objects. If none match, it rotates original evergreen objects. A search trend is not proof of a viral video.
- Makes short original scripts, captions and four original illustrated title cards. An optional OpenAI-compatible text API can replace the built-in scripts. The built-in renderer uses Pillow, FFmpeg and `espeak-ng` (simple synthetic voice). This is a functional prototype, not a photorealistic text-to-video model.
- Uploads videos to Cloudinary and passes their stable public HTTPS URLs to Buffer. The same Indonesian MP4 is used for Instagram and TikTok. YouTube gets an English MP4.
- Checks the exact Buffer slot before posting to avoid duplicate posts on a rerun. If that check fails, the pipeline fails closed. No API keys are stored in the repository or artifacts.
- **Safe default:** creates preview MP4s and a JSON manifest; does not contact Buffer or Cloudinary unless `LIVE_PUBLISH=true` and all required settings exist.

## Required GitHub settings for publishing

In repository Settings → Secrets and variables → Actions:

| Type | Name | Meaning |
| --- | --- | --- |
| Secret | `BUFFER_API_KEY` | Personal Buffer key with posts read/write |
| Variable | `BUFFER_ORGANIZATION_ID` | Buffer organization ID |
| Variable | `BUFFER_INSTAGRAM_CHANNEL_ID` | ZunoLoop professional Instagram channel |
| Variable | `BUFFER_TIKTOK_CHANNEL_ID` | ZunoLoop TikTok channel |
| Variable | `BUFFER_YOUTUBE_CHANNEL_ID` | ZunoLoop YouTube channel |
| Secret | `CLOUDINARY_CLOUD_NAME` | Cloudinary cloud name |
| Secret | `CLOUDINARY_API_KEY` | Cloudinary API key |
| Secret | `CLOUDINARY_API_SECRET` | Cloudinary API secret |
| Variable | `LIVE_PUBLISH` | Set to `true` only after checking previews and channel IDs |

Optional content API: `CONTENT_API_URL` (HTTPS OpenAI-compatible chat completions endpoint), `CONTENT_MODEL`, `CONTENT_API_KEY` (Secret). ChatGPT Plus does not provide API credits for a GitHub runner. If absent or unavailable, original built-in scripts are used.

Do not paste secrets in Issues, workflow files, logs, or this repository. The Buffer key created earlier expires after 30 days and needs rotation before then. Connected channels in Buffer must permit automatic publishing.

## Try before publishing

1. Run **Actions → ZunoLoop daily video pipeline → Run workflow** with `LIVE_PUBLISH` unset. Download the video previews in the workflow artifact.
2. Check language, speech, frame layout and channel mappings.
3. Configure Cloudinary and Buffer values privately, then set `LIVE_PUBLISH=true`. Run once manually; inspect the six Buffer scheduled entries before relying on the daily schedule.

Local preview: `python -m pip install -r requirements.txt && python -m zunoloop.pipeline` after installing FFmpeg, espeak-ng and DejaVu fonts. Test: `python -m unittest discover -s tests`.

## Limits

GitHub Actions scheduled jobs may start late; the job has a 45-minute limit. Buffer fetches the Cloudinary URL at publication time, so keep the asset public until all three posts are sent. The Cloudinary free allowance and any optional model free quota can change. This system does not guarantee views, follower growth, or affiliate revenue. Videos containing only cards and synthetic voice should be reviewed before live automation.

API references: [Buffer video](https://developers.buffer.com/examples/create-video-post.html), [Buffer scheduling](https://developers.buffer.com/guides/posts-and-scheduling.html), [media hosting](https://developers.buffer.com/guides/hosting-media.html), [Cloudinary signed upload](https://cloudinary.com/documentation/authentication_signatures).
