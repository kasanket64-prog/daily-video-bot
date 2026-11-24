# GTA VI clips: setup and operating guide

## What the cloud workflow does

Cloudflare's scheduled Worker wakes the Render clip service. Render checks the configured creator/campaign feeds, captures recent GTA VI clips or live moments, ranks them, and asks the Worker to inspect strong candidates. Passing files are sent to the private Telegram chat with per-video approval buttons. Your computer can be off.

The active configured sources are KreekCraft, Clix, and Lacy. They are not a universal search across every stream. Each creator/campaign has its own eligibility, attribution, timing, and editing rules; the system must keep those restrictions. A public stream URL by itself is not reuse permission. The bot should hold a source when it cannot establish the required campaign or reuse rights.

## Clip quality and delivery

- Keep the original stream sound and clear speech. Reject silent, garbled, unrelated, routine, or unfinished moments.
- Select only a specific chaotic, surprising, or funny event with a comprehensible setup and payoff. Do not claim virality.
- Target an 18-second edit, move the selected activity into roughly the first five seconds, show the complete payoff, and end with a brief event-specific viewer question. Keep the creator's original stream audio; the question is on-screen text, not extra voiceover.
- Keep the black-background layout, creator credit, and required campaign labels. Every candidate must pass inspection before Telegram delivery.
- Each Telegram preview needs its own approval. No approval means no upload.
- Approved GTA posts publish at the next 9:00 AM India time slot. Approval before 9:00 AM is queued for that morning; approval at or after 9:00 AM is queued for the next morning. If several are approved, each platform keeps its 10-minute spacing, so later posts follow the first in order.
- YouTube and Instagram uploads remain paced independently by `GTA_UPLOAD_GAP_SECONDS=600` (10 minutes; allowed range 300–600 seconds). The five-minute Worker schedule and upload processing can make the actual publication a few minutes later than the target.
- A daily Telegram status notice reports when no fresh eligible clip is found or all candidates fail inspection. Cloud service errors also produce a Telegram notice.
- Instagram stays paused until its account connection is complete. YouTube and Instagram each have separate upload states, so one destination can finish while the other waits.

## Campaigns and earnings

The bot prepares campaign-suitable clips for the campaign sources it has configured. It does not automatically enroll in new campaigns, accept changing campaign terms, or submit campaign links to the rewards site. After a campaign clip publishes, Telegram sends one message with its post URL, campaign link, and the 30-minute deadline. Submit the post on the campaign site yourself, then tap **Mark submitted** on that same message. A public post is not guaranteed to qualify for a reward; check that campaign's rules and deadline.

## Current operating setup

The service uses Cloudflare Workers and D1 for scheduling, credentials, approvals, state, and publishing; GitHub Actions for the reviewed-source rendering workflow; Render for the live clipper; and Telegram for approvals. Free hosting can sleep, throttle, or become unavailable. It cannot guarantee 30–40 usable clips per day, continuous stream coverage, views, or earnings.

Keep credentials in Cloudflare Worker Secrets. Do not put Google, Meta, Telegram, or provider tokens in GitHub or in this repository. Relevant nonsecret Worker settings are:

| Setting | Purpose |
|---|---|
| `GTA_REELS_ENABLED` | Enables the GTA publishing workflow |
| `LIVE_WATCH_ENABLED` | Enables cloud checks for configured live sources |
| `LIVE_RENDER_URL` | Render clip-service address |
| `LIVE_CHANNEL_ID` | Expected GTA VI channel identity |
| `GTA_UPLOAD_GAP_SECONDS` | Publication spacing; default 600 seconds, allowed 300–600 |
| `YOUTUBE_PRIVACY` | YouTube visibility; use `private` for initial verification |
| `INSTAGRAM_ENABLED` | Leave disabled while Instagram is paused |

Use `GET /health` to confirm the Worker is reachable and the Render `/health` page to view its last run. In the Render status, `stage: clip_lookup` with zero deliveries means the service did not find a fresh eligible clip in that check; `stage: inspection` with held candidates means quality checks rejected them. A zero-view YouTube Short is not automatically proof of a broken upload; inspect its status and allow analytics time to update.

## First run after code changes

1. Deploy `cloudflare/worker.mjs` and the matching `cloudflare/wrangler.jsonc` settings to the existing Worker. Keep the existing D1 database and cron binding.
2. Confirm Telegram, YouTube, and Render connection status without sharing secrets in chat.
3. Run one manual clip check and inspect the actual Telegram preview, audio, labels, and source attribution.
4. Approve one preview and verify the resulting YouTube upload. Instagram remains paused until its own account setup is complete.
5. Review the Content Rewards campaign page for any separate link-submission deadline after a post goes live.

See [README](README.md) for the project overview and [CONTENT_ENGINE](CONTENT_ENGINE.md) for source-rights and review design.

