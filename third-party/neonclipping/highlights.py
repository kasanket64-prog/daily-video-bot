"""Independent highlight ranking v2: optical-flow motion + audio spikes, in parallel.

Signals (all local, no model download):
  motion  - OpenCV Farneback optical flow at 160x90, 90th-percentile magnitude per second (fast objects,
            explosions, car flips); hard scene cuts are detected and excluded from motion, counted as cut density.
  audio   - loudness JUMP vs the local 2-minute baseline (sudden boom/shout beats constantly loud music).
  shout   - share of 2-4 kHz energy (voices raised, screams, impacts) weighted by loudness jump.
  cuts    - editing/camera-cut density.
The source is split into time chunks decoded by parallel FFmpeg processes (decode is the bottleneck).
Candidates only; semantic re-ranking happens in smart.py.
"""
import os, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np, cv2

FPS = 3; W, H = 160, 90; CUT = 38.0   # mean abs diff above this = hard cut

def _chunk(source, start, length, report):
    cmd = ['ffmpeg', '-v', 'error', '-ss', f'{start}', '-t', f'{length}', '-i', str(source), '-an',
           '-vf', f'fps={FPS},scale={W}:{H}', '-pix_fmt', 'gray', '-f', 'rawvideo', 'pipe:1']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=W * H * 64)
    flow, cuts, prev, n = [], [], None, 0
    try:
        while True:
            raw = p.stdout.read(W * H)
            while raw and len(raw) < W * H:
                more = p.stdout.read(W * H - len(raw))
                if not more: break
                raw += more
            if len(raw) != W * H: break
            cur = np.frombuffer(raw, np.uint8).reshape(H, W)
            if prev is None: flow.append(0.); cuts.append(0.)
            else:
                if float(np.mean(cv2.absdiff(cur, prev))) > CUT: flow.append(0.); cuts.append(1.)
                else:
                    f = cv2.calcOpticalFlowFarneback(prev, cur, None, .5, 2, 9, 2, 5, 1.1, 0)
                    flow.append(float(np.percentile(np.hypot(f[..., 0], f[..., 1]), 90))); cuts.append(0.)
            prev = cur; n += 1
        p.wait()
    finally:
        if p.poll() is None: p.kill(); p.wait()
        p.stdout.close()
    report(length)
    k = len(flow) // FPS * FPS
    f = np.array(flow[:k]).reshape(-1, FPS).mean(1) if k else np.zeros(0)
    c = np.array(cuts[:k]).reshape(-1, FPS).sum(1) if k else np.zeros(0)
    return f, c

def _motion(source, duration, report):
    workers = max(2, min(12, (os.cpu_count() or 4) - 2))
    size = max(60, int(np.ceil(duration / workers / 60) * 60))          # whole-minute chunks
    starts = list(range(0, int(np.ceil(duration)), size))
    done = [0.]
    def rep(sec): done[0] += sec; report(min(done[0], duration))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(_chunk, source, s, min(size, duration - s), rep): s for s in starts}
        parts = {jobs[j]: j.result() for j in as_completed(jobs)}
    f = np.concatenate([parts[s][0] for s in starts]) if starts else np.zeros(0)
    c = np.concatenate([parts[s][1] for s in starts]) if starts else np.zeros(0)
    return f, c

def _audio(source):
    cmd = ['ffmpeg', '-v', 'error', '-i', str(source), '-vn', '-ac', '1', '-ar', '8000', '-f', 's16le', 'pipe:1']
    raw = subprocess.run(cmd, capture_output=True).stdout
    x = np.frombuffer(raw[:len(raw) // 2 * 2], np.int16).astype(np.float32) / 32768
    n = len(x) // 8000
    if n == 0: return np.zeros(0), np.zeros(0)
    x = x[:n * 8000].reshape(n, 8000)
    rms = np.sqrt((x ** 2).mean(1))
    spec = np.abs(np.fft.rfft(x * np.hanning(8000), axis=1)) ** 2          # 1 Hz bins
    hf = spec[:, 2000:4000].sum(1) / (spec.sum(1) + 1e-9)
    return rms, hf

def _z(x, n, win=120):
    """Local z-score vs a rolling baseline, clipped to 0..1 (z of 3.5 = 1)."""
    out = np.zeros(n)
    if not len(x): return out
    y = np.zeros(n); y[:min(n, len(x))] = x[:n]
    win = max(1, min(win, n)); k = np.ones(win) / win
    mu = np.convolve(y, k, 'same'); sd = np.sqrt(np.maximum(np.convolve(y * y, k, 'same') - mu * mu, 0)) + 1e-6
    return np.clip((y - mu) / sd / 3.5, 0, 1)

def rank(source, duration, count=4, length=30, report=lambda seconds: None, motion_on=True, extra=None):
    with ThreadPoolExecutor(max_workers=2) as pool:
        m = pool.submit(_motion, source, duration, report) if motion_on else pool.submit(lambda: (np.zeros(0), np.zeros(0))); a = pool.submit(_audio, source)
        (flow, cuts), (rms, hf) = m.result(), a.result()
    n = max(1, int(np.ceil(duration)))
    has_audio = len(rms) > 0
    motion = _z(flow, n); cut = _z(cuts, n)
    loud = _z(rms, n) if has_audio else np.zeros(n)
    shout = np.clip(_z(hf * rms, n) if has_audio else np.zeros(n), 0, 1)
    sig = (.35 * motion + .30 * loud + .20 * shout + .15 * cut) if motion_on and has_audio else (.55 * loud + .45 * shout) if has_audio else (.7 * motion + .3 * cut)
    if extra is not None and len(extra):                 # what is SAID (exclamations) attracts candidates too
        e = np.zeros(n); e[:min(n, len(extra))] = extra[:n]
        sig = .75 * sig + .25 * e
    width = min(n, 7); smooth = np.convolve(sig, np.ones(width) / width, 'same')
    length = min(float(length), duration); clips = []
    for center in np.argsort(smooth)[::-1]:
        start = max(0, min(float(center) - length * .4, duration - length)); end = min(duration, start + length)
        if any(min(end, c['end']) - max(start, c['start']) > 0 for c in clips): continue
        parts = {'motion': motion, 'audio jump': loud, 'shouting': shout, 'cuts': cut}
        lo, hi = int(start), max(int(start) + 1, int(end))
        top = sorted(parts, key=lambda k: -parts[k][int(center) - 3:int(center) + 4].mean() if len(parts[k]) else 0)[:2]
        clips.append({'start': round(start, 2), 'end': round(end, 2), 'title': f'Activity highlight {len(clips) + 1}',
                      'score': round(float(smooth[center]) * 100 / max(float(smooth.max()), 1e-6)),
                      'reason': 'Peak: ' + ' + '.join(top), 'status': 'done',
                      'features': {'loud': float(loud[lo:hi].mean()) if has_audio else None, 'shout': float(shout[lo:hi].mean()) if has_audio else None,
                                   'motion': float(motion[lo:hi].mean()) if motion_on else None, 'cuts': float(cut[lo:hi].mean()) if motion_on else None}})
        if len(clips) >= count: break
    if not clips: clips = [{'start': 0, 'end': round(length, 2), 'title': 'Review source opening', 'score': 0, 'reason': 'No strong activity peak found', 'status': 'done'}]
    return clips
