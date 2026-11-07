# Milo & Pip cartoon renderer

The renderer now accepts original story JSON with 24–60 five-second scenes and exports a 2–5-minute landscape YouTube episode plus a 20-second vertical highlight for Shorts/Reels. The existing 30-second Lost Ball pilot command remains available.

`examples/cartoon-story.json` is a two-minute example. Each scene provides one short narration line and one supported action (`idle`, `walk`, `search`, `find`, `return`, `play`, `celebrate`). The Short uses the highest-scoring four-scene window, favoring discovery, return, and celebration beats. Change the story JSON to make another episode; the renderer does not invent a new story by itself.

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

The checks verify 30-second duration, dimensions, frame count, an audible finite audio track, caption layout, motion, and scene continuity. Six decoded frames from each output form contact sheets for visual review. These checks do not replace watching/listening to the pilot, and the Gemini inspector is not connected to this pilot yet.

## Current limits and next stage

Daily story generation is held while this style is reviewed. The Cloudflare Worker inspector was built for the previous fitness format and still needs child-suitability and story-continuity checks. Daily unique-story generation, grouped Telegram approval, YouTube made-for-kids configuration, and Instagram authorization remain to be completed. No social upload is part of this renderer workflow. GitHub Actions availability and Microsoft Edge TTS availability are external free-tier dependencies and are not guaranteed permanently.
