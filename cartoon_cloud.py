"""Prepare, inspect and deliver the two cartoon previews through Cloudflare."""
import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from bot import APIError, http
from cloud_render import identity, worker_url

ROOT = Path(__file__).resolve().parent


def post(worker, route, data=None, content_type=None):
    headers = {'Authorization': 'Bearer ' + identity(worker)}
    if content_type:
        headers['Content-Type'] = content_type
    return http('POST', worker + route, headers=headers, data=data, timeout=360)


def prepare():
    worker = worker_url()
    result = post(worker, '/render/cartoon-story', {})
    jobs = post(worker, '/render/cartoon-jobs', {})
    if len(jobs.get('jobs', [])) != 2 or any(not item.get('owned') for item in jobs['jobs']):
        raise RuntimeError('Today’s cartoon jobs already exist or could not be reserved')
    work = ROOT / 'work'
    work.mkdir(exist_ok=True)
    (work / 'cartoon-story.json').write_text(json.dumps(result['story'], ensure_ascii=False), encoding='utf-8')
    (work / 'cartoon-jobs.json').write_text(json.dumps(jobs['jobs']), encoding='utf-8')
    print(f"Prepared today's story: {result['story']['title']}")


def inspect_and_send(worker, job, path):
    data = path.read_bytes()
    if not 0 < len(data) <= 19_000_000:
        raise RuntimeError(f'{path.name} exceeds Telegram’s 19 MB review limit')
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)]))
    duration = float(probe['format']['duration'])
    streams = probe['streams']
    video = next(stream for stream in streams if stream['codec_type'] == 'video')
    expected = (720, 1280) if job['short'] else (1280, 720)
    minimum, maximum = (15, 32) if job['short'] else (120, 300)
    if not minimum <= duration <= maximum or (video['width'], video['height']) != expected or not any(s['codec_type'] == 'audio' for s in streams):
        raise RuntimeError(f'{path.name} failed duration, dimensions, or audio checks')
    frames = []
    for fraction in (.04, .18, .35, .52, .72, .92):
        scale = '360:640' if job['short'] else '640:360'
        frame = subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', str(duration * fraction), '-i', str(path),
            '-frames:v', '1', '-vf', f'scale={scale}', '-f', 'image2pipe', '-vcodec', 'mjpeg', '-q:v', '4', '-threads', '1', '-'])
        frames.append(base64.b64encode(frame).decode('ascii'))
    audio = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path), '-vn', '-ac', '1',
        '-ar', '16000', '-b:a', '24k', '-f', 'mp3', '-'])
    report = post(worker, '/render/inspect/' + job['id'], {
        'sha256': hashlib.sha256(data).hexdigest(), 'duration': duration, 'frames': frames,
        'audio': base64.b64encode(audio).decode('ascii')
    })
    if report.get('passed') is not True:
        raise RuntimeError(f'{path.name} was held by the automatic cartoon inspector')
    post(worker, '/render/preview/' + job['id'], data, 'video/mp4')
    print(f'Sent inspected preview to private Telegram: {path.name}')


def deliver():
    worker = worker_url()
    jobs = json.loads((ROOT / 'work' / 'cartoon-jobs.json').read_text(encoding='utf-8'))
    for job in jobs:
        if job.get('status') != 'generating':
            print(f"Skipping {job['id']}: its review state is already {job['status']}.")
            continue
        filename = 'highlight-short.mp4' if job['short'] else 'episode-youtube.mp4'
        inspect_and_send(worker, job, ROOT / 'cartoon-output' / filename)


def failed():
    post(worker_url(), '/render/cartoon-failure', {})
    print('Sent a failure notice to the private Telegram chat.')


if __name__ == '__main__':
    try:
        actions = {'prepare': prepare, 'deliver': deliver, 'failed': failed}
        if len(sys.argv) != 2 or sys.argv[1] not in actions:
            raise RuntimeError('Use: python cartoon_cloud.py prepare|deliver|failed')
        actions[sys.argv[1]]()
    except Exception as error:
        if isinstance(error, APIError):
            print(str(error))
        print(f'Cartoon workflow stopped: {type(error).__name__}. Check the Worker configuration and run state.')
        raise SystemExit(1)
