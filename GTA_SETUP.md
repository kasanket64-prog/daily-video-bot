# Set up your GTA VI Reel bot

GitHub renders gameplay in the cloud. Cloudflare holds the account credentials and records your Telegram decisions. Each daily run can prepare up to 40 distinct clips. Telegram sends each inspected live preview with its own approval buttons as soon as it is ready.

## 1. Install the update

Merge the reviewed `shorts-preview-test` branch into `main` in [your repository](https://github.com/kasanket64-prog/daily-video-bot/compare/main...shorts-preview-test). The Worker accepts jobs from the workflow on `main`. In Cloudflare Workers & Pages, open **daily-video-approvals → Edit code** and deploy the contents of [worker.mjs](cloudflare/worker.mjs) from that same commit. Keep the existing D1 binding named `DB` and the five-minute cron trigger. For a new D1 database, run [schema.sql](cloudflare/schema.sql) in its console first.

## 2. Connect the existing accounts

In **Worker → Settings → Variables and Secrets**, keep your existing working settings. Store private values as **Secret**. Use fresh Google upload credentials if your previous ones appeared in a screenshot.

| Purpose | Worker settings |
|---|---|
| Identify your deployment | `WORKER_URL`, `REPOSITORY`, `REPOSITORY_ID`, `OWNER_ID` from [the project configuration](cloudflare/wrangler.jsonc) |
| Look up source videos and inspect clips | `YOUTUBE_DATA_API_KEY`, `GEMINI_API_KEY` |
| Send previews to your phone | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_USER_ID`, `TELEGRAM_WEBHOOK_SECRET`. Start the bot in your private Telegram chat. |
| Publish an approved Short | `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` for the intended channel. Set `YOUTUBE_PRIVACY=private` for the first upload. |
| Publish an approved Reel | `INSTAGRAM_USER_ID`, `INSTAGRAM_ACCESS_TOKEN` for the linked professional account, and its supported `META_API_VERSION` |

Set the Worker variables `GTA_REELS_ENABLED=true` and `SHORT_PREVIEW_TEST=true` for the first preview. In [GitHub Actions variables](https://github.com/kasanket64-prog/daily-video-bot/settings/variables/actions), add `GTA_REELS_ENABLED=true` and `CLOUDFLARE_WORKER_URL` with the HTTPS origin of your Worker. These two GitHub values are public configuration. All account credentials belong in Cloudflare.

## 3. Add a stream

Copy [the GTA source template](examples/gta-source.json) into a Worker secret named `REVIEWED_SHORT_SOURCES`. Replace each placeholder with details of a recording you have permission to edit and publish on YouTube and Instagram. The bot needs both the YouTube video ID and a direct HTTPS media-file link up to 1 GB supplied by the creator. Record the agreed credit and permission evidence and set the clearance flags accurately. Add further recordings to the same JSON array.

## 4. Receive your first preview

Open [Scout trends for Shorts](https://github.com/kasanket64-prog/daily-video-bot/actions/workflows/trend-scout.yml), select **Run workflow**, choose **main**, and run it. With preview testing enabled, an eligible recording produces at most one private Telegram test video. If none arrives, open the run and check whether it found the source, rendered a highlight, and passed inspection.

## 5. Start daily operation

After reviewing the test video, set the **Worker** variable `SHORT_PREVIEW_TEST=false`. The workflow requests a daily run at 06:07 India time and also supports manual runs. GitHub can delay scheduled runs. A production preview arrives with **Approve upload** and **Reject**. Only the individual file you approve enters the upload queue. If you want public YouTube uploads, change `YOUTUBE_PRIVACY` to `public` when ready.

The editor groups nearby changes in sound and movement, leaves a little setup and payoff, and fits each clip within the [three-minute YouTube Shorts format](https://support.google.com/youtube/answer/15424877). The actual daily count depends on approved footage, successful inspections and free quotas. Your computer can be off.
