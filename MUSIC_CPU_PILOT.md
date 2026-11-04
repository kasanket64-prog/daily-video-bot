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

Model download, dependency installation and inference have not yet been tested
on the cloud runner. Upstream specifies about 10 GB of core models; disk and
16 GB RAM may be insufficient. This is a feasibility test, not a daily service.
Weights are downloaded by upstream; their revisions are not pinned by this
prototype. Installed dependency versions also need recording from a successful
run before treating this as reproducible production infrastructure.

Accept only after listening and checking the exact words:

    Wings go up, wings go down,
    Little Pip stays on the ground.

An audible file does not establish accurate singing, musical quality or
synchronization with the existing video. Keep daily publishing disabled.
