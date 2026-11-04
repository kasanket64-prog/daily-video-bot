# CPU music benchmark

Manual experiment only. No schedule, keys, account signup, phone verification,
external inference API or social publishing. Run on the standard Linux GitHub
runner in this public repository; do not change it to a paid/larger runner.

Workflow: **Benchmark original rhyme on CPU**. It uses a pinned official
ACE-Step source revision, the smaller 2B turbo model, CPU-only PyTorch, no
optional language model, one sample, ten seconds and eight inference steps.
The job stops after 50 minutes; generation has its own 30-minute limit.

Download the `pip-cpu-rhyme-benchmark` artifact. `benchmark.json` records audio
duration, peak amplitude, elapsed time and peak process memory when Python can
finish writing it. `process-resources.txt` also records process resource use.
An OOM kill or job timeout can prevent a complete report or artifact.

Cloud benchmark succeeded on 2026-11-04:
https://github.com/kasanket64-prog/daily-video-bot/actions/runs/41806600631
Model download, installation and CPU inference completed. The output is ten
seconds at 48 kHz; Python measured 101.33 seconds including loading/downloads,
and 14,260 MiB peak resident memory. The complete job took about three minutes.
No GPU or personal credentials were used. Singing quality and exact lyrics
have not been reviewed. Memory is close to the standard runner limit; longer
generation remains untested. This is a feasibility test, not a daily service.
Weights are downloaded by upstream; their revisions are not pinned by this
prototype. Installed dependency versions also need recording from a successful
run before treating this as reproducible production infrastructure.

Accept only after listening and checking the exact words:

    Wings go up, wings go down,
    Little Pip stays on the ground.

An audible file does not establish accurate singing, musical quality or
synchronization with the existing video. Keep daily publishing disabled.
