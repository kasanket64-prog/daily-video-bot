# Daily video bot — free cloud setup

Creates one original short video from a current Indian Google Trends topic, chooses English or Hindi, sends a Telegram preview around **09:00 Asia/Kolkata**, and uploads to YouTube and Instagram **only after the configured owner approves that exact preview**.

**Status: implementation prepared; not activated or end-to-end tested with real credentials.** Connecting GitHub alone does not connect Telegram, Google, Pexels, or Meta. No video has been generated or published by this setup yet.

## How it works

1. At about 06:47 India time, a GitHub-hosted Linux job reads India's current search-trend feed. Gemini writes an original short explainer and chooses English/Hindi. A trending search is a topic signal, not proof it is the most viewed video.
2. A pinned MoneyPrinterTurbo source checkout (`ab6004e5858998b2ce99ac46c0f16675eea9ab6f`) combines the script, free Pexels footage, Edge speech, subtitles, and portrait video. Paid MPT providers and automatic cross-posting are disabled. FFmpeg creates a 720×1280 preview.
3. GitHub stores the exact video and metadata as a short-lived artifact. The controller checks Telegram every 30 minutes; its first check at or after 09:00 sends the preview and Approve both / Reject buttons. If today's preview isn't ready, it sends a status message instead.
4. An approval from your configured private Telegram chat/user enters the publishing queue. Each platform uploads independently via its official API. Missing platform credentials leave that platform waiting; they do not authorize another destination.
5. Rejection prevents publishing. Duplicate button clicks do not post again. A checksum binds the preview to the uploaded file. Uploads with an uncertain outcome stop for manual inspection instead of risking duplicates.

Your computer is not needed at runtime. GitHub's free scheduler can be delayed or drop runs; neither exactly 09:00 nor instant uploading can be guaranteed. Approval processing normally waits up to 30 minutes, plus runner and upload delays. Public-repository schedules can be disabled after 60 days without repository activity; regularly verify the Actions page and maintain the software.

## ₹0 requirement

- Keep this repository public and use only the included **standard** GitHub-hosted runner. No paid runner, n8n, server, domain, or subscription is required.
- In GitHub billing, configure a **$0 budget with usage stopping enabled** for Actions/storage if your account has a payment method. Free compute does not make artifact storage unlimited. The bot retains videos for two days, limits each to 49 MB, and refuses generation if this repository's active artifacts approach 200 MB. Other repositories may share your storage allowance: the account budget is the final guard.
- Create the Gemini API key on a project with **no paid billing attached**, and use a model available in that project's free tier. The default is `gemini-2.5-flash`; confirm it is still offered free when setting up. Set the `GEMINI_MODEL` variable to a supported free model if necessary. Free-tier availability and quotas vary. The bot stops on errors; it has no paid fallback.
- Obtain a free Pexels API key. This version uses stock footage, not paid generative-video services. There is no guaranteed viral reach or revenue.
- Google Drive is optional and is not used in this implementation; GitHub artifacts provide short-term storage. This keeps the number of account connections smaller.

## Ponytail coding extension

The project includes Ponytail's official agent instructions in `AGENTS.md` and six project skills in `.agents/skills`: `ponytail`, `ponytail-review`, `ponytail-audit`, `ponytail-debt`, `ponytail-gain`, and `ponytail-help`. They guide coding and review; they are not part of video generation or publishing and add no runtime service or subscription.

Open this project in an agent that supports `AGENTS.md` / project skills, then start a new chat so it discovers them. This is the upstream-supported instruction-and-skills installation, not a global Codex plugin installation. Lifecycle hooks, persistent level switching, and statusline integration are not installed. Existing approval and publishing behavior is unchanged.

Source: [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail), pinned to commit `96608e078b2d5ea607c5c3b8b5a54d1c1fba6846`. The upstream MIT license is retained in `third-party/ponytail/LICENSE`.

## Install in kasanket64-prog/daily-video-bot

Upload all package contents to the repository root, including the **.github/workflows** directory. Alternatively use git to commit them. GitHub integrations may need explicit Contents and Workflows write access; account `push` permission alone does not grant an integration these permissions.

Create the secrets below in **Settings → Secrets and variables → Actions → Secrets**. Never put them in code, commits, issues, screenshots, or chat messages.

| Secret | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Token from the official [@BotFather](https://t.me/BotFather), using `/newbot` |
| `TELEGRAM_USER_ID` | Your numeric Telegram user ID, not your username |
| `TELEGRAM_CHAT_ID` | Your private chat's numeric ID |
| `GEMINI_API_KEY` | AI Studio key on a project without paid billing |
| `PEXELS_API_KEY` | Free key from [Pexels API](https://www.pexels.com/api/) |
| `YOUTUBE_CLIENT_ID` | Google OAuth desktop application client ID |
| `YOUTUBE_CLIENT_SECRET` | Matching OAuth client secret |
| `YOUTUBE_REFRESH_TOKEN` | Offline authorization for your actual channel with `youtube.upload` scope |
| `INSTAGRAM_USER_ID` | Professional Instagram account's numeric ID |
| `INSTAGRAM_ACCESS_TOKEN` | Meta token with content-publishing access using the Facebook Login for Business route |

Create repository **Variables**:

| Variable | Value |
| --- | --- |
| `AUTOMATION_ENABLED` | Leave unset until setup/testing finishes; later set `true` |
| `GEMINI_MODEL` | Optional free-tier model, default `gemini-2.5-flash` |
| `META_API_VERSION` | Supported Meta Graph API version for your app, e.g. a currently supported `vNN.N`; consult the app dashboard |
| `YOUTUBE_PRIVACY` | Use `private` for the first test; change to `public` for subsequent approved videos |

`GITHUB_TOKEN` is supplied by Actions automatically; do not create a personal token for the bot. Workflows need Contents write and Actions read. `bot-state` is created automatically; all controllers share a concurrency group to serialize state writes. Main-branch code is the source of truth.

## Telegram setup

1. Create a dedicated bot in the official @BotFather chat using `/newbot`.
2. Open your new bot, press Start, and send a message. It cannot initiate the first private conversation itself.
3. Use Telegram's official `getUpdates` API to read that message's `from.id` and `chat.id` in a trusted local tool, then add the IDs as repository secrets. The bot uses polling, so it must not have a webhook or another application consuming its updates. Do not send the token to a third-party ID bot.
4. Once deployed, `Approve both` authorizes publishing that video's exact preview to your configured accounts. No response leaves it pending until it expires. Artifacts last two days; approvals expire 40 hours after generation.

## Connect publishing accounts

**YouTube:** enable YouTube Data API v3 in your Google project, create an OAuth client, and obtain offline authorization for the channel using Google's supported OAuth flow and `https://www.googleapis.com/auth/youtube.upload`. Keep billing disabled. Check current Google OAuth app eligibility, quota, and verification requirements; testing-mode refresh tokens may expire. Set privacy to `private` initially. This implementation declares videos not made for children; change the code if your channel is intended for children. Platform processing can finish after the upload response.

**Instagram:** this implementation uses the **Facebook Login for Business / graph.facebook.com resumable upload route**, not an Instagram Login token or a personal Instagram account. Use an eligible professional account and linked Facebook Page, configure a Meta developer app, and grant the required Instagram content-publishing and Page permissions. Obtain the account ID and appropriate token through Meta's official tools. App mode, roles, permission review, and token lifetime affect availability. The controller refreshes neither Meta nor Telegram credentials; replace expiring credentials before they fail. The binary upload route avoids requiring a public video-hosting service.

These account authorizations require your participation. No password sharing is needed. A free plan does not remove the platforms' eligibility or OAuth requirements.

## Validate and activate

1. Run **Actions → Check bot → Run workflow**. It runs fifteen focused tests without account credentials.
2. Configure the secrets and free-usage guards. Set `YOUTUBE_PRIVACY=private` and `AUTOMATION_ENABLED=true`.
3. Manually run **Generate daily preview** once. Inspect the Actions result. Generation is reserved once per India calendar day; repeated runs will not silently generate another video. A failed reserved generation must be investigated before retrying on a later day.
4. Run **Telegram approval and publishing** after 09:00 India time (or wait for its schedule). Review the full preview, title, caption, language, and source links. Test rejection first. Test a real approval on a subsequent day's preview with both social accounts connected.
5. Confirm the private YouTube test upload and Instagram upload in the actual accounts. Set YouTube privacy to public only when satisfied. Verify Hindi glyph shaping, pronunciation, subtitle timing, footage relevance, and factual claims with a real rendered video. Those media checks have not been performed here.
6. Monitor the first few scheduled runs. Missing credentials, exhausted free quotas, token expiry, source changes, or account restrictions can stop automation. Receive Telegram failures when the controller can reach Telegram; infrastructure/install failures may appear only in GitHub Actions.

To pause everything, remove `AUTOMATION_ENABLED` or set it to `false`. Existing public posts are not removed.

## Failure recovery and privacy

- Never blindly clear a `started` or `needs_review` platform result: an interrupted upload may already exist. Inspect that platform and record its media ID in `bot-state/state.json`, or establish that it did not publish before intentionally clearing that one platform entry. A successful other platform result must be preserved. Changes should be made with the workflows paused.
- An interrupted `sending_preview` is held instead of automatically sending a second preview; inspect Telegram and reconcile its message ID with state before resuming.
- The public `bot-state` branch contains job dates, status, checksums, artifact IDs, Telegram message numbers, and published platform IDs. It never stores account IDs, credentials, OAuth session URLs, scripts, or raw Telegram updates. **Artifacts in a public repository are not a private vault**: GitHub users with applicable access can download them. Use this for nonsensitive public-intended content only. A private repository requires evaluating its free compute/storage allowance separately; these workflows deliberately refuse to run there.
- The scheduled job only approves callback buttons, not arbitrary Telegram text or forwarded links. Owner, private chat, message ID, expiry, and current state must all match.
- AI script generation uses headline context rather than live full-article fact verification. Source links are supplied for human review. The bot must not be treated as a verified breaking-news reporter. It creates original narration with licensed stock footage rather than downloading trending creators' videos.
- Artifact expiry removes pending media; the implementation has no long-term archive. Persisted state records remain for audit/recovery.

## Checks performed during preparation

Fifteen offline unit tests passed: approval ownership and expiry, rejection, malformed callbacks, duplicate clicks, partial platform failure, interrupted upload handling, no upload without approval, video and metadata checksum mismatches, account-connection notices, malformed AI output, clean generation reruns, registration across midnight, and authorization-header removal on artifact redirects. Python syntax was checked. No real generation, Telegram message, social upload, cloud schedule, or GitHub Actions run was performed with user credentials. Deployment and media/API compatibility still require the live checks above.

References: [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo), [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [schedule limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule), [Gemini free tier](https://ai.google.dev/gemini-api/docs/pricing), [Telegram Bot API](https://core.telegram.org/bots/api), [YouTube upload API](https://developers.google.com/youtube/v3/docs/videos/insert), [Meta's official Reels sample](https://github.com/fbsamples/reels_publishing_apis/tree/main/insta_reels_publishing_api_sample).
