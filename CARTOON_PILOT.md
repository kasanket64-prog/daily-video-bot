# Milo & Pip cartoon renderer

The renderer accepts original story JSON with 24–60 five-second scenes and exports a 2–5-minute landscape episode plus a 20-second vertical highlight. The cloud story generator currently creates a two-minute English or Hindi Milo & Pip episode. The existing 30-second Lost Ball pilot command remains available.

The scheduled/manual cloud workflow requests one original two-minute story from the Cloudflare Worker, saves it by India-local date, then renders a landscape episode and a vertical highlight. Re-running it that day reuses the same story and will not send duplicate previews already in review. Each scene provides one short narration line and one supported action (`idle`, `walk`, `search`, `find`, `return`, `play`, `celebrate`). The Short uses the highest-scoring four-scene window, favoring discovery, return, and celebration beats. `examples/cartoon-story.json` remains a sample for local rendering.

The assets are original illustrations; motion uses 2D sprite transforms, expressions, camera framing, and the animated ball. It is not full 3D character animation or a text-to-video diffusion model. Scene actions currently control a small set of reusable motions, so story text must match what those characters and the garden can visibly do. There is no lip-sync rig yet.

The renderer uses open-source Pillow, NumPy, PyAV/FFmpeg, and Edge TTS. Speech requires the free external Microsoft speech endpoint; availability is not guaranteed. The quiet soundtrack and bounce/discovery tones are synthesized locally from an original note pattern, with no downloaded songs. Reusing the saved art requires no paid image-generation API.

## Run locally or on a free public GitHub Actions runner

Python 3.12 or later:

```sh
python -m pip install -r requirements-cartoon.txt
python cartoon_pilot.py --output pilot-output
python cartoon_pilot.py --story-json examples/cartoon-story.json --output episode-output
python cartoon_selfcheck.py pilot-output
```

On Linux, install `fonts-dejavu-core` and `fonts-noto-core` for English and Hindi captions. The **Render original cartoon episode and Short** workflow requests today's story, renders both formats, inspects their frames and full narration, sends the exact files to your private Telegram chat, and saves a review artifact for three days. It does not contain publishing credentials or publish anything; the Worker holds the private account credentials.

## Connect the cloud workflow

Before enabling the workflow, deploy the updated `cloudflare/worker.mjs` to the existing Worker, keep `GEMINI_API_KEY` in Cloudflare Secrets, and make sure the bound D1 database has the existing `settings` table. Add the HTTPS Worker origin as the GitHub Actions variable `CLOUDFLARE_WORKER_URL`. Set `CARTOON_AUTOMATION_ENABLED=true` as both a Cloudflare Worker variable and a GitHub repository variable; leave the old fitness `AUTOMATION_ENABLED` switch off. The Worker checks GitHub's short-lived OIDC identity and accepts this workflow only from `main`. No Gemini or social account key is needed in GitHub.

The local pilot self-check verifies its 30-second duration, dimensions, frame count, audio, caption layout, motion, and scene continuity. The cloud workflow separately asks the Worker's Gemini inspector to check six frames, the complete narration, child suitability, and story continuity before Telegram delivery. This automated check can miss issues; watch and listen to both previews yourself.

## Current limits and next stage

The workflow is scheduled for 6:00 AM India time, leaving time to render before the Worker adds approval buttons at or after 9:00 AM. GitHub may delay scheduled runs, so those times are not guaranteed. This separate switch does not start the retired fitness workflow. The episode targets YouTube with the Made for Kids flag; the vertical Short targets YouTube and Instagram. Each file has its own approval button. If an account is not connected, its upload remains waiting. Story variety is prompted and exact narration repeats are rejected, but semantic uniqueness is not guaranteed. GitHub Actions, Gemini free-tier quotas, and Microsoft Edge TTS availability can change.
