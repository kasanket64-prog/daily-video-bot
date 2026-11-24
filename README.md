# Fit-zee GTA Clips Bot

A cloud-hosted workflow for finding fresh GTA VI livestream moments, editing candidate Shorts, inspecting them, and sending each passing clip to Telegram for approval. Approved clips can be published to connected platforms. It runs on Cloudflare, GitHub Actions, and the configured live-clip service; your computer does not need to stay on.

## Start here

- [GTA setup and operating guide](GTA_SETUP.md)
- [Content selection, rights checks, and inspection design](CONTENT_ENGINE.md)
- [GTA source template](examples/gta-source.json)

## Current safeguards

- Only approved clips are published; Telegram approval is required for every video.
- The live workflow checks reviewed campaign sources and rejects routine moments, unclear audio, and clips that fail inspection.
- Live clips target 18 seconds, bring the activity peak earlier, and end with a factual on-screen question while preserving the stream audio.
- A daily Telegram status notice explains when the cloud check found no fresh clip or when candidates failed inspection.
- Approved GTA clips are queued for 9:00 AM India time; late approvals move to the next day's slot. Multiple approved clips follow at 10-minute intervals per platform.
- After a campaign clip publishes, Telegram sends one post message with the video link, campaign link, deadline, and a **Mark submitted** button. Joining campaigns and submitting on the campaign site remain manual.
- `GTA_UPLOAD_GAP_SECONDS` defaults to 600 (10 minutes) and accepts 300–600 seconds.
- The system aims for strong moments, not a guaranteed number of clips or views. Source availability, campaign eligibility, free hosting limits, and quality checks can reduce output.

## Current project limitation

The bot can only clip streams that its configured discovery sources can access and that meet the relevant creator or campaign rules. A public stream link alone does not grant permission to reuse its footage. If no allowed source is available, the bot will report that in Telegram instead of silently claiming a clip was created.

