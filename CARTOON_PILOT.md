# Milo & Pip: The Lost Ball

One 30-second original style pilot, exported as landscape (1280×720) and vertical (720×1280), at 24 fps. This tests the creative direction before making full 2–3-minute episodes.

The short story has six beats: Milo plays with a ball, loses it behind flowers, Pip arrives, finds it, returns it, and the friends play together. The assets are original generated illustrations; motion uses 2D sprite transforms, expressions, occlusion, camera framing, and an animated ball. It is not full 3D character animation or a text-to-video diffusion model. There is no lip-sync rig yet.

The renderer uses open-source Pillow, NumPy, PyAV/FFmpeg, and Edge TTS. Speech requires the free external Microsoft speech endpoint; availability is not guaranteed. The quiet soundtrack and bounce/discovery tones are synthesized locally from an original note pattern, with no downloaded songs. Reusing the saved art requires no paid image-generation API.

## Run locally or on a free public GitHub Actions runner

Python 3.12 or later:

```sh
python -m pip install -r requirements-cartoon.txt
python cartoon_pilot.py --output pilot-output
python cartoon_selfcheck.py pilot-output
```

On Linux, install `fonts-dejavu-core`. Windows uses Arial Bold. The manual **Render original cartoon pilot** workflow installs dependencies, renders both formats, checks the actual files, and retains the review artifact for three days. It has Contents read permission only. It never accesses publishing credentials or uploads to social accounts.

The checks verify 30-second duration, dimensions, frame count, an audible finite audio track, caption layout, motion, and scene continuity. Six decoded frames from each output form contact sheets for visual review. These checks do not replace watching/listening to the pilot, and the Gemini inspector is not connected to this pilot yet.

## Current limits and next stage

Daily generation is held while this style is reviewed. The existing Worker inspector was built for the previous fitness format and must be adapted for child suitability, story continuity, and the two approved files. The full-episode script, long-video renderer, highlight selection, grouped Telegram approval, YouTube made-for-kids setting, and Instagram authorization remain to be completed. No social upload is part of this pilot.
