# ZunoLoop daily video pipeline

At 09:00 WIB, GitHub Actions prepares two Indonesian shorts for Instagram and TikTok, and two English shorts for YouTube. The Indonesian videos are each scheduled on both channels, for six Buffer posts a day. Planned times are 12:00 and 20:00 WIB for Indonesia, and 19:00 and 21:00 New York time for YouTube. Late runs move missed slots to the next day.

## Status and content quality

The `create` job generates four 12-second 9:16 MP4 previews and a manifest. It succeeded on GitHub Actions before this media-hosting revision. The renderer uses simple title-card animation and `espeak-ng` voices; it is **not AI text-to-video**. Google Trends ID/US feeds only help choose among safe talking-object topics; they do not prove a topic or the resulting video is viral. Optional OpenAI-compatible text API settings can write new scripts. ChatGPT Plus itself does not run inside GitHub Actions or include API credits.

The `publish` job runs only with `LIVE_PUBLISH=true`. It copies MP4s into `site/media`, retains seven days, deploys the site through GitHub Pages, verifies that the MP4 URL is public, then schedules two posts on each of the three connected Buffer channels. GitHub Pages serves the video to Buffer until publication. A GitHub Free account requires this repository to be **public** for Pages. Generated MP4 files committed under `site/media` will also be public. No API credential belongs in the code or media.

## Configuration

The three non-sensitive Buffer channel IDs are repository variables:

| Variable | Connected channel |
| --- | --- |
| `BUFFER_INSTAGRAM_CHANNEL_ID` | Instagram Professional ZunoLoop |
| `BUFFER_TIKTOK_CHANNEL_ID` | TikTok ZunoLoop |
| `BUFFER_YOUTUBE_CHANNEL_ID` | YouTube ZunoLoop |

The workflow obtains the Buffer organization ID itself and confirms that all three channel IDs match the expected platform. Add a repository **secret** named `BUFFER_API_KEY` through GitHub Settings → Secrets and variables → Actions. The key must have posts read/write. Buffer personal keys expire and require rotation. Never paste a key in a commit, issue, log, or variable.

To activate live publishing, enable GitHub Pages with **Build and deployment → Source: GitHub Actions**, then set the repository variable `LIVE_PUBLISH=true`. Before activation, `create` keeps only a private seven-day preview artifact. The workflow's publish job fails closed if the key, channel mapping, Pages deployment, or public video URL is unavailable. Do not turn on `LIVE_PUBLISH` before the repository can serve public media.

Optional content API: `CONTENT_API_URL` (HTTPS OpenAI-compatible chat completions endpoint) and `CONTENT_MODEL` as variables, `CONTENT_API_KEY` as a secret. If absent, built-in original scripts are used.

Local preview: install FFmpeg, espeak-ng and DejaVu fonts, then run `python -m pip install -r requirements.txt && python -m zunoloop.pipeline`. Unit checks: `python -m unittest discover -s tests`.

## Limits

GitHub scheduled jobs can start late. Buffer may reject a channel's media or publishing settings; inspect the first live workflow and the six scheduled posts before relying on the schedule. GitHub Pages may need a few moments to serve the freshly deployed MP4. This system cannot guarantee views, followers, affiliate income, or a viral topic. Its current title-card videos need creative improvement before becoming a high-quality content channel.

Primary references: [Buffer video](https://developers.buffer.com/examples/create-video-post.html), [Buffer scheduling](https://developers.buffer.com/guides/posts-and-scheduling.html), [Buffer media hosting](https://developers.buffer.com/guides/hosting-media.html), [GitHub Pages availability](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages).
