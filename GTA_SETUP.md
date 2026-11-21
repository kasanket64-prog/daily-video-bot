# Set up your GTA VI Reel bot

## Unattended NeonClipping service

The recurring deployment uses Cloudflare's five-minute cron and the Free web service at https://gta-neon-live.onrender.com. The service runs the original MIT-licensed NeonClipping highlight detector from revision `3a3da401`. It checks Lacy's current Twitch broadcast and its GTA VI marathon title, captures a short window, ranks sound and visual activity, and prepares up to two candidates per check. Source IDs follow the actual Twitch broadcast automatically. The setup runs independently of this chat and the owner's computer.

Each cut enlarges Lacy's facecam above the gameplay and includes `Ad | #LACY` and the stream credit. Stream audio is muted in this deployment. The final inspection requires a visible setup and payoff and checks campaign suitability before sending the exact file to Telegram. Each file needs its own owner approval. An inspector can hold every candidate in a window. Views and daily output depend on the footage.

Cloudflare keeps `LIVE_WATCH_ENABLED=true`, `LIVE_RENDER_URL`, and `LIVE_CHANNEL_ID` as configuration. It keeps the private signing key and callback secret in Worker Secrets. Render has only the public verification key. Each work request carries temporary callback access, and the service cannot select a different creator or bypass final-file inspection. D1 keeps the daily slots, source intervals, upload state and last dispatch/result across service restarts. Existing preview testing can stay enabled because the live route has its own authenticated approval flow.

The free host provides 0.1 CPU and 512 MB RAM. Processing can take several minutes, and capture windows leave gaps between checks. Render may restart or suspend free services under its published usage limits. A restart discards temporary video and the next cron retries. A daily failure notice goes to Telegram when the scheduler or clipper reports an error. Free hosting has no continuous-coverage guarantee and cannot guarantee 30–40 worthwhile clips every day.

To pause capture, set the Worker's `LIVE_WATCH_ENABLED=false`. Pausing also holds pending live uploads. YouTube remains private until its visibility setting is changed. Instagram requires its own connected account before that destination can finish.

The historical GitHub runner instructions below describe the development and pilot path. The recurring live video service uses Render.

GitHub renders gameplay in the cloud. Cloudflare holds the account credentials and records your Telegram decisions. Each daily run can prepare up to 40 distinct clips. Telegram sends each inspected live preview with its own approval buttons as soon as it is ready.

## How the GTA workflow fits together

One scheduled GitHub Actions job handles the heavy video work. One Cloudflare Worker with a D1 database handles credentials, review decisions and publishing. Telegram is the owner's review screen. Your computer can be off.

| Stage | Where it runs | What moves to the next stage |
|---|---|---|
| 1. Match recordings | Cloudflare and YouTube | The daily GTA path looks up videos already listed in the private source catalog. The entry supplies the direct media link, creator credit and permission evidence. A popular stream can be a lead. Its rights must be reviewed before it enters the catalog. |
| 2. Pick distinct moments | GitHub Actions | Download each selected recording once per run. Scan its sound and picture together. Group nearby reactions, keep setup and payoff, and exclude time ranges that overlap the previous 30 days of reservations for that source. Visual activity also catches quiet moments. |
| 3. Edit the shortlist | GitHub Actions | Load the CPU speech model once when the first moment needs editing. Transcribe selected segments, add timed captions and credit, preserve cleared audio, and export one vertical MP4 for both platforms. |
| 4. Inspect the finished cut | Runner, Cloudflare and Gemini | Check format and duration locally. Send six frames and the full clip audio for inspection. A passing result records the file fingerprint. Sending different bytes requires a fresh inspection. Held clips consume a slot and stay out of the approval queue. |
| 5. Decide on the phone | Telegram and D1 | Each daily production preview has its own Approve and Reject buttons. The Worker checks the owner's identity, private chat, message, expiry and pending status. |
| 6. Upload and reconcile | Cloudflare | The five-minute job processes approved clips. YouTube and Instagram have separate upload states and IDs. A missing connection can leave one destination waiting. Check the platform before retrying an upload with an uncertain outcome. |

The daily scheduler requests a run at 06:07 India time. Preview delivery follows inspection as each cut finishes. A 09:00 batch or digest would need its own delivery rule. The current bounds are 40 daily slots, a 175-minute runner timeout, a 1 GB download per recording and a scan of its first two hours. These are capacity limits. The number worth publishing depends on the footage and the owner's decisions.

### Where the next efficiency gains are

1. **Measure usable output on a real stream.** Use the same cleared long recording for the baseline and trial. Record source bytes fetched, elapsed runner minutes, distinct moments, inspections passed, Telegram decisions and successful uploads per platform. Compare **runner minutes per owner-approved Reel**. If no clip earns approval, report the counts instead of dividing by zero. Track approval quality separately from upload failures.
2. **Trial selective downloads with a suitable source.** The current direct-MP4 route downloads the whole file. Where the creator provides a separately accessible audio track and seekable video, scan the audio first and fetch candidate windows with room for setup and payoff. Include a low-resolution visual pass or compare against the full scan on quiet scenes. Measure actual bytes transferred. Keep the full-file route for hosts without efficient seeking and for recordings where the fast route misses worthwhile visual moments.
3. **Improve presentation where the source warrants it.** For streams with a facecam, test a reaction-above-gameplay layout against the current full-frame fit. Check that the game HUD and payoff stay visible. For Hindi commentary, compare Hinglish captions against the transcript and check names before approval. These are candidates from [NeonClipping](https://github.com/iamajmeena/neonclipping). Neither requires running a desktop editor as part of the daily job.
4. **Scale after a complete cloud trial.** First verify one ordinary catalog recording from discovery through Telegram, then verify an owner-approved upload on each connected platform. Compare several daily runs under the free quota before committing to 30–40 previews per day. An empty catalog should finish without rendering. A thin stream should produce fewer clips.

The combined scan was checked on the 11.0 MB night-fishing sample. The old and new scans produced identical audio levels, motion values and highlights at 00:05–00:18 and 00:24–00:37. Across six alternating local runs of each version, median scan time was 1.330 seconds before and 1.297 seconds after. This measures scanning only. Long-stream cloud throughput and download savings still need the trial above.

### Watch a stream while it is live

The optional watcher checks reviewed YouTube broadcast IDs for live status. It picks the highest-ranked eligible live feed and keeps up to two minutes of recent gameplay per scan. Overlapping segments are reused. A reaction at the edge of the window waits for its payoff. The editor identifies the moment by time since the broadcast began, so overlapping windows and repeat runs refer to the same event. A first pass scores changes in sound and motion. Inspection checks whether a viewer can understand the setup, see or hear the payoff, and trust the caption. The owner makes the final decision on Telegram.

1. In the private source catalog, add the usual rights and credit fields for the broadcast. Use its YouTube ID, add `"media_kind": "live-hls"`, and set `media_url` to the creator-provided HTTPS **media playlist**. The YouTube watch page identifies the stream. The creator's feed supplies timestamped, unencrypted MPEG-TS segments from the same host. The watcher requires at least 18 seconds of contiguous video. Up to two minutes of playlist history helps it catch the beginning and end of a reaction.
2. For a pilot, run **Scout trends for Shorts** manually on main and select **Watch a reviewed live GTA feed**. With the Worker's preview test enabled, this sends up to one private test clip. An offline broadcast uses no rendering or inspection.
3. For recurring watches, enable the production approval flow from step 5 and set the GitHub variable `GTA_LIVE_WATCH_ENABLED=true`. The workflow requests a check every 15 minutes. An active session polls between edits for up to 14 minutes, sharing the 40 daily slots with recordings. It watches one eligible feed at a time. Runner queues, time spent rendering and short playlist histories can leave gaps.

The live regression test generates a rolling stream with a reaction across segment boundaries. It checks that the editor waits for the finish, selects the moment once and fetches each overlapping segment once. A real creator feed and end-to-end platform approvals are separate operational checks.

## 1. Install the update

Use the reviewed workflow on [the main branch](https://github.com/kasanket64-prog/daily-video-bot/tree/main). The Worker accepts jobs from that branch. For a new deployment or a Worker code update, deploy [worker.mjs](cloudflare/worker.mjs) from the same revision in Cloudflare. Keep the existing D1 binding named `DB` and the five-minute cron trigger. For a new D1 database, run [schema.sql](cloudflare/schema.sql) in its console first.

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
