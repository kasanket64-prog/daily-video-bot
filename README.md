# Daily video bot — credentials stay outside GitHub

This revision uses **Cloudflare Workers Free + D1 Free** for private configuration, script preparation, Telegram approval, job state, and publishing. GitHub Actions only renders video. No account token or provider key is configured as a GitHub Secret or sent to its runner.

Status: cloud automation enabled and Telegram webhook connected. The first live cloud render and Telegram preview delivery succeeded on 4 November 2026 ([run](https://github.com/kasanket64-prog/daily-video-bot/actions/runs/41716904942)). All 19 Python and 9 Worker checks pass. Social publishing awaits owner approval and is not yet verified. YouTube currently uploads privately; Instagram authorization is pending.

## Daily behavior

- GitHub starts a standard Linux rendering job around 06:47 India time.
- It proves its repository/workflow identity to Cloudflare with GitHub OIDC. There is no shared API password in GitHub. Trust is restricted to this repository ID, owner ID, main branch, exact workflow, and scheduled/manual events.
- Cloudflare reads Indian Google search trends, creates an original English/Hindi script with Gemini, and searches free Pixabay footage. It sends only the script and public media URLs to GitHub.
- If Pixabay is rate-limited or has no matching clips, the renderer creates an original background with narration and captions. Approval identifies this fallback; no paid stock service is used.
- MoneyPrinterTurbo renders with local clips and free Edge speech. GitHub sends the finished file directly to Cloudflare. No workflow artifact or account credential is stored in GitHub.
- A silent Telegram preview is prepared earlier in the morning. At the first Cloudflare five-minute check at/after 09:00 India time, approval buttons are attached and a notification is sent. Exact delivery time is not guaranteed by the free schedules.
- Approve upload saves approval for that exact Telegram file and names the configured destinations. Cloudflare checks the owner, private chat, message ID, expiry and pending status. Rejection or no approval prevents publication.
- Cloudflare uploads independently to YouTube and, when configured, Instagram. YouTube-only jobs finish without waiting for Instagram. A started/interrupted upload is held for inspection to avoid duplicates. Instagram may take another five-minute check to finish processing.
- Previews expire after 40 hours. Video files must remain below 19 MB so the free Telegram file API can retrieve them for publication. This implementation is for short nonsensitive clips intended for public posting.

Your computer can stay off after setup. The earlier polling implementation in bot.py is superseded; active workflows do not invoke its account-handling functions. Its HTTP transport is reused by cloud_render.py.

## What goes where

**GitHub repository Variables only** (not Secrets):

| Name | Value |
| --- | --- |
| CLOUDFLARE_WORKER_URL | Your Worker HTTPS origin, without a trailing slash |
| AUTOMATION_ENABLED | Leave unset/false until the live test is ready |

GitHub automatically supplies temporary job identity. Personal GitHub tokens and Cloudflare API tokens are not needed for the renderer. The workflow has Contents read and ID-token write permissions; checkout does not persist credentials.

**Cloudflare Worker Secrets only**:

| Name | Purpose |
| --- | --- |
| TELEGRAM_BOT_TOKEN | BotFather token |
| TELEGRAM_USER_ID | Owner's numeric Telegram user ID |
| TELEGRAM_CHAT_ID | Owner's private chat ID |
| TELEGRAM_WEBHOOK_SECRET | A new random value using letters, numbers, underscores or hyphens; at least 32 characters |
| GEMINI_API_KEY | Gemini project key with paid billing disabled |
| PIXABAY_API_KEY | Free Pixabay API key |
| YOUTUBE_CLIENT_ID | Your Google OAuth client ID |
| YOUTUBE_CLIENT_SECRET | Matching client secret |
| YOUTUBE_REFRESH_TOKEN | Offline authorization for the actual channel with youtube.upload scope |
| INSTAGRAM_USER_ID | Professional Instagram account ID |
| INSTAGRAM_ACCESS_TOKEN | Authorized Facebook Login for Business route token |

Cloudflare ordinary Variables: WORKER_URL (same origin), REPOSITORY, REPOSITORY_ID, OWNER_ID, GEMINI_MODEL, YOUTUBE_PRIVACY, META_API_VERSION, AUTOMATION_ENABLED. The repository identity defaults are in cloudflare/wrangler.jsonc. Use a currently supported Meta version. Start YouTube with private visibility. Do not place actual secrets in wrangler.jsonc or any file committed to GitHub.

## Cloudflare setup

1. Stay on Workers Free; no paid upgrade, domain purchase, R2 bucket or paid service is needed.
2. Create a Worker named daily-video-approvals. Deploy cloudflare/worker.mjs as its module source. Initially leave AUTOMATION_ENABLED=false. GET /health should return an enabled:false response, with no credentials.
3. Create a free D1 database named daily-video-bot. In its SQL console execute cloudflare/schema.sql. Bind it to the Worker with binding name DB. The example wrangler configuration uses a placeholder database ID; replace that ID only if deploying with Wrangler.
4. In Worker Settings → Variables and Secrets, add the account values above as Secrets. You must enter private tokens yourself; do not send them in chat or put them on GitHub.
5. Set the nonsecret variables from the example config, including WORKER_URL. Keep paid Gemini billing disabled; use a model offered by your account's free tier. Pixabay is used because new Pexels API-key issuance is currently paused.
6. Add a Cron Trigger: */5 * * * *. Cron syntax is UTC. The code converts to India time before sending the daily notification.
7. Set AUTOMATION_ENABLED=true in Cloudflare only when ready to test. The first cron verifies the Telegram webhook and configures it with its secret header. This dedicated bot must not be used simultaneously by another webhook or polling app.
8. In GitHub Variables set CLOUDFLARE_WORKER_URL, then AUTOMATION_ENABLED=true. Run Generate daily preview manually once. Approve only after inspecting its content. Verify both real account uploads before relying on daily operation.

Token setup: use the official BotFather, Google AI Studio, Pixabay API documentation, Google OAuth flow, and Meta developer tools. YouTube requires offline user authorization, not a password or generic service account. Instagram uses the Facebook Login for Business / graph.facebook.com resumable route with an eligible professional account and linked Page. OAuth app eligibility, review, quota and token expiry still apply on free services.

## Free limits and recovery

Keep Workers and D1 on their Free plans and the GitHub repository public with standard runners. Set a $0 blocking GitHub billing budget if a payment method exists on the account. Free quotas and platform eligibility are not guaranteed. Do not attach billing to the Gemini project. No paid fallback is implemented.

Large video transfers, memory use, cryptographic validation and uploads need a real Worker Free runtime test. Offline tests cannot establish that every provider call fits the free CPU/network limits. If a free runtime limit is reached, stop and adjust the implementation rather than enabling a paid plan.

D1 stores private job metadata and Telegram file/message IDs. Worker Secrets store account credentials. Public health returns only service name and enabled status. Provider errors are sanitized; observability is disabled by default. Job failures are reported to the owner's Telegram when reachable. Missing credentials keep publication waiting.

Inspect jobs left in sending_preview, notifying, started, or publishing states before retrying: the external operation may already have succeeded. Do not clear successful platform IDs. Pause both AUTOMATION_ENABLED switches before manually repairing state. Failed preparation with no metadata or video can be retried explicitly; there is no automatic loop consuming AI quota.

The Worker authenticates to a fixed repository subject of repo:OWNER/REPO:ref:refs/heads/main. If your GitHub organization enables a different OIDC subject format, update and test the explicit allowlist; do not remove subject/owner/repository checks.

## Checks and limitations

18 Python tests and 6 Node tests passed during preparation. They cover legacy controller regressions, the no-GitHub-Secrets workflow invariant, renderer URL restrictions, signed OIDC validation and tampering, approval ownership/expiry, malformed scripts, RSS parsing, and safe disabled endpoints. They do not replace real D1/concurrency, rendering, Hindi text shaping, Worker Free runtime, account-token or social upload tests.

Trending searches are topic signals, not proof of most-viewed content. AI scripts use headline context and may contain inaccuracies; check the preview and sources before approving. Stock footage may be generic. There is no promise of views or revenue.

Ponytail project instructions and six coding/review skills remain included under AGENTS.md and .agents/skills, pinned to upstream commit 96608e078b2d5ea607c5c3b8b5a54d1c1fba6846. Its MIT license is in third-party/ponytail/LICENSE. It adds no runtime subscription.
