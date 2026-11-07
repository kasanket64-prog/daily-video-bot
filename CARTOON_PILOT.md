# Milo & Pip cartoon renderer

The renderer now accepts original story JSON with 24–60 five-second scenes and exports a 2–5-minute landscape YouTube episode plus a 20-second vertical highlight for Shorts/Reels. The existing 30-second Lost Ball pilot command remains available.

The manual cloud workflow requests one original two-minute story from the Cloudflare Worker, saves it by India-local date, then renders a landscape episode and a vertical highlight. Re-running it that day reuses the same story. Each scene provides one short narration line and one supported action (`idle`, `walk`, `search`, `find`, `return`, `play`, `celebrate`). The Short uses the highest-scoring four-scene window, favoring discovery, return, and celebration beats. `examples/cartoon-story.json` remains a sample for local rendering.

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

On Linux, install `fonts-dejavu-core` and `fonts-noto-core` for English and Hindi captions. The manual **Render original cartoon episode and Short** workflow runs the example story and saves the review files as an artifact for three days. It has Contents read permission only. It never accesses publishing credentials or uploads to social accounts.

## Connect the manual cloud workflow

Before running it, deploy the updated `cloudflare/worker.mjs` to the existing Worker, keep `GEMINI_API_KEY` in Cloudflare Secrets, and make sure the bound D1 database has the existing `settings` table. Add the HTTPS Worker origin as the GitHub Actions variable `CLOUDFLARE_WORKER_URL`. Run **Render original cartoon episode and Short** from the repository's `main` branch; the Worker checks GitHub's short-lived OIDC identity and accepts this workflow only from `main`. No Gemini key is needed in GitHub. The endpoint works while upload automation is disabled because it only creates and saves a story.

The checks verify 30-second duration, dimensions, frame count, an audible finite audio track, caption layout, motion, and scene continuity. Six decoded frames from each output form contact sheets for visual review. These checks do not replace watching/listening to the pilot, and the Gemini inspector is not connected to this pilot yet.

## Current limits and next stage

The story-generation endpoint is ready but needs the updated Worker deployed. The cloud workflow is still manual and saves an artifact only; it does not send videos to Telegram or upload them. Daily scheduling, child-safety review, grouped Telegram approval, YouTube made-for-kids configuration, and Instagram authorization remain to be completed. GitHub Actions, Gemini free-tier quotas, and Microsoft Edge TTS availability can change.
