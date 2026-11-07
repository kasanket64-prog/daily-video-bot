"""Original reusable-art cartoon renderer. CPU rendering; no paid generation API.

Run: python cartoon_pilot.py --output DIRECTORY
Long episode: add --story-json examples/cartoon-story.json
Dependencies: Pillow, numpy, av, edge-tts. This is a style pilot, not the daily publisher.
"""
import argparse
import asyncio
import hashlib
import io
import json
import math
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ASSETS = Path(__file__).resolve().parent / 'assets/cartoon'
FPS = 24
SCENE_SECONDS = 5
LINES = [
    'Milo loved his bright red ball.',
    'Oops! It bounced behind the flowers!',
    'Pip saw Milo looking for it.',
    'Here it is! chirped little Pip.',
    'Thank you, Pip! Milo smiled.',
    'Helping a friend makes playtime happier.'
]


def smooth(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


def story_state(seconds, scenes=None):
    if scenes is not None:
        scene = min(len(scenes)-1, int(seconds / SCENE_SECONDS))
        phase = (seconds % SCENE_SECONDS) / SCENE_SECONDS
        targets = {
            'idle': (.32, .82), 'walk': (.56, .82), 'search': (.58, .88),
            'find': (.58, .70), 'return': (.45, .57), 'play': (.34, .70),
            'celebrate': (.34, .66),
        }
        action = scenes[scene]['action']
        previous = scenes[max(0, scene-1)]['action']
        blend = smooth(phase / .22)
        start_bunny, start_bird = targets[previous]
        end_bunny, end_bird = targets[action]
        bunny = start_bunny + (end_bunny-start_bunny)*blend
        bird = start_bird + (end_bird-start_bird)*blend
        ball_visible = action in ('find', 'return', 'play', 'celebrate')
        ball = .48 + .10*math.sin(phase*math.tau) if action in ('play', 'celebrate') else bird-.08
        if action == 'walk':
            ball = .48 + .40*smooth(phase)
            ball_visible = True
        if action == 'find':
            ball = .88-.32*smooth(phase)
            ball_visible = phase > .42
        elif action == 'return':
            ball = bird-.10
        return {'scene': scene, 'phase': phase, 'bunny': bunny, 'bird': bird,
                'ball': ball, 'ball_visible': ball_visible, 'worried': action == 'search',
                'action': action}
    scene = min(5, int(seconds / SCENE_SECONDS))
    phase = (seconds % SCENE_SECONDS) / SCENE_SECONDS
    state = {'scene': scene, 'phase': phase, 'bunny': 0.28, 'bird': 1.15,
             'ball': 0.44, 'ball_visible': True, 'worried': scene in (1, 2)}
    if scene == 1:
        state['ball'] = 0.44 + 0.45 * smooth(phase / 0.8)
        state['ball_visible'] = phase < 0.82
    elif scene == 2:
        state['bird'] = 1.1 - 0.25 * smooth(phase / 0.85)
        state['ball_visible'] = False
    elif scene == 3:
        state['bird'] = 0.85 - 0.21 * smooth(phase)
        state['ball'] = state['bird'] - 0.08
        state['ball_visible'] = phase > 0.12
    elif scene == 4:
        state['bird'] = 0.64
        state['ball'] = 0.56 - 0.12 * smooth(phase)
    elif scene == 5:
        state['bird'] = 0.64
        state['ball'] = 0.47 + 0.12 * math.sin(phase * math.tau)
    return state


def font_path(language='en'):
    candidates = ([Path('/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf'),
                   Path('C:/Windows/Fonts/mangal.ttf')]
                  if language == 'hi' else []) + [
        Path('C:/Windows/Fonts/arialbd.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
        Path('/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf'),
    ]
    return next(path for path in candidates if path.exists())


class Stage:
    def __init__(self, width, height, language='en'):
        self.width, self.height = width, height
        self.language = language
        self.portrait = height > width
        self.background = ImageOps.fit(Image.open(ASSETS / 'garden.png').convert('RGB'), (width, height), centering=(0.52, 0.48))
        self.characters = {}
        for name in ('milo', 'milo-worried', 'pip'):
            image = Image.open(ASSETS / (name + '.png')).convert('RGBA')
            # Crop only transparent margins; retain the original artwork and alpha.
            image = image.crop(image.getchannel('A').point(lambda a: 255 if a > 20 else 0).getbbox())
            size = int(height * (0.36 if self.portrait else 0.58)) if name.startswith('milo') else int(height * (0.23 if self.portrait else 0.35))
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            self.characters[name] = image
        self.caption_font = ImageFont.truetype(str(font_path(language)), 30 if self.portrait else 29)
        self.small_font = ImageFont.truetype(str(font_path(language)), 20)
        self.bush = Image.open(ASSETS/'bush.png').convert('RGBA')
        self.bush = self.bush.crop(self.bush.getchannel('A').point(lambda a: 255 if a > 20 else 0).getbbox())
        self.bush.thumbnail((round(width*.25), round(height*.25)), Image.Resampling.LANCZOS)

    def character(self, frame, name, center, ground, angle=0, bounce=0):
        sprite = self.characters[name].rotate(angle, Image.Resampling.BICUBIC, expand=True)
        shadow = Image.new('RGBA', frame.size)
        draw = ImageDraw.Draw(shadow)
        radius = sprite.width * 0.29
        draw.ellipse((center-radius, ground-8, center+radius, ground+8), fill=(42, 90, 46, 55))
        frame.alpha_composite(shadow)
        frame.alpha_composite(sprite, (round(center-sprite.width/2), round(ground-sprite.height-bounce)))

    def render(self, seconds, scenes=None, title='Milo & Pip', local_seconds=None):
        state = story_state(seconds, scenes)
        scene, phase = state['scene'], state['phase']
        w, h = self.width, self.height
        frame = self.background.convert('RGBA')
        ground = h * (0.77 if self.portrait else 0.83)
        # Original fireflies / pollen move independently of the painted background.
        draw = ImageDraw.Draw(frame)
        for index in range(8):
            x = (index * w / 7 + seconds * (5 + index % 3)) % w
            y = h * 0.26 + math.sin(index + seconds * 0.65) * h * 0.11
            draw.ellipse((x, y, x+4, y+4), fill=(255, 246, 193, 160))
        bunny = state['bunny'] * w
        bird = state['bird'] * w
        action = state.get('action', 'idle')
        hop = max(0, math.sin(seconds * 4.2)) * (13 if action in ('play', 'celebrate') else 3)
        bird_lift = (18 + 12 * math.sin(seconds * 6)) if action in ('search', 'find', 'return') else max(0, math.sin(seconds * 5))*8
        self.character(frame, 'milo-worried' if state['worried'] else 'milo', bunny, ground,
                       math.sin(seconds*2.2) * (2 if state['worried'] else 3), hop)
        self.character(frame, 'pip', bird, ground - h*0.01, math.sin(seconds*5)*5, bird_lift)
        draw = ImageDraw.Draw(frame)
        if state['ball_visible']:
            radius = int(w * (0.046 if self.portrait else 0.028))
            x = state['ball'] * w
            y = ground - radius - (abs(math.sin(seconds * 5)) * h * 0.12 if scene in (0, 1, 5) else h*0.025)
            draw.ellipse((x-radius, ground-5, x+radius, ground+6), fill=(53, 100, 58, 75))
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill='#f65f68', outline='#b82e51', width=3)
            draw.arc((x-radius+7, y-radius+7, x+radius-7, y+radius-7), 195, 280, fill='#ffc7ba', width=5)
            draw.line((x-radius+4, y+radius*0.25, x+radius-4, y-radius*0.2), fill='#ffd37c', width=6)
        # Foreground flowers visibly occlude the lost ball.
        frame.alpha_composite(self.bush, (round(w*.91-self.bush.width/2), round(ground-self.bush.height*.94)))
        # Different camera framings give each story beat a purpose.
        if not self.portrait:
            action = state.get('action', 'idle')
            zoom, focus = {'idle': (1.0,.5), 'walk': (1.12,.68), 'search': (1.36,.29),
                           'find': (1.25,.7), 'return': (1.08,.48), 'play': (1.0,.5),
                           'celebrate': (1.0,.5)}[action] if scenes is not None else [(1.0,.5),(1.12,.68),(1.36,.29),(1.25,.7),(1.08,.48),(1.0,.5)][scene]
            zoom += .025 * smooth(phase)
            crop_w, crop_h = w/zoom, h/zoom
            left = max(0,min(w-crop_w,w*focus-crop_w/2))
            top = max(0,min(h-crop_h,h*.54-crop_h/2))
            frame = frame.crop((round(left),round(top),round(left+crop_w),round(top+crop_h))).resize((w,h),Image.Resampling.LANCZOS)
        # A title identifies the pilot; captions remain short and visually safe.
        local_seconds = seconds if local_seconds is None else local_seconds
        if local_seconds < 3.8:
            title_font = ImageFont.truetype(str(font_path(self.language)), 30 if self.portrait else 35)
            self.center_text(frame, 'MILO & PIP', h*.06, title_font, '#fff4cf', '#31585b')
            self.center_text(frame, title, h*.06+48, self.small_font, '#ffffff', '#31585b')
        caption = (scenes[scene]['line'] if scenes is not None else LINES[scene])
        words = caption.split()
        lines, current = [], ''
        max_width = w - 60
        for word in words:
            candidate = f'{current} {word}'.strip()
            if current and ImageDraw.Draw(frame).textbbox((0,0), candidate, font=self.caption_font)[2] > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        caption_y = h * .82
        line_height = self.caption_font.size + 8
        overlay = Image.new('RGBA', frame.size)
        od = ImageDraw.Draw(overlay)
        widths = [od.textbbox((0,0), line, font=self.caption_font)[2] for line in lines]
        box_w = min(w-30, max(widths)+44)
        od.rounded_rectangle(((w-box_w)/2, caption_y-12, (w+box_w)/2, caption_y+len(lines)*line_height+8), radius=18, fill=(20, 45, 50, 195))
        frame.alpha_composite(overlay)
        for index, line in enumerate(lines):
            self.center_text(frame, line, caption_y+index*line_height, self.caption_font, '#ffffff')
        if (state.get('action') == 'celebrate' or (scenes is None and scene == 5)) and phase > .2:
            # Small celebratory stars; no flashing or rapid cuts.
            draw = ImageDraw.Draw(frame)
            for index in range(6):
                x = w*(.35+index*.06); y = ground-h*.55 + math.sin(seconds*2+index)*12
                draw.regular_polygon((x,y,6), 4, rotation=45, fill='#ffe39a')
        return frame.convert('RGB')

    @staticmethod
    def center_text(frame, text, y, font, fill, stroke=None):
        draw = ImageDraw.Draw(frame)
        width = draw.textbbox((0,0), text, font=font)[2]
        draw.text(((frame.width-width)/2, y), text, font=font, fill=fill,
                  stroke_width=2 if stroke else 0, stroke_fill=stroke)


def load_story(path):
    story = json.loads(path.read_text(encoding='utf-8'))
    actions = {'idle', 'walk', 'search', 'find', 'return', 'play', 'celebrate'}
    if not isinstance(story, dict):
        raise ValueError('Story file must contain a JSON object')
    scenes = story.get('scenes')
    if not isinstance(story.get('title'), str) or not 1 <= len(story['title']) <= 45:
        raise ValueError('Story title must contain 1–45 characters')
    if story.get('language', 'en') not in ('en', 'hi'):
        raise ValueError('Story language must be en or hi')
    if not isinstance(scenes, list) or not 24 <= len(scenes) <= 60:
        raise ValueError('A long episode needs 24–60 five-second scenes (2–5 minutes)')
    for index, scene in enumerate(scenes):
        if (not isinstance(scene, dict) or not isinstance(scene.get('line'), str)
                or not 1 <= len(scene['line']) <= 110 or len(scene['line'].split()) > 14
                or scene.get('action') not in actions):
            raise ValueError(f'Scene {index+1} needs a short narration line and a supported action')
    return story


async def speech(directory, lines, language):
    import edge_tts
    voice = 'hi-IN-SwaraNeural' if language == 'hi' else 'en-US-AnaNeural'
    for line in lines:
        cache_key = hashlib.sha256((voice + '\0' + line).encode('utf-8')).hexdigest()[:20]
        destination = directory / f'{cache_key}.mp3'
        if not destination.exists():
            await edge_tts.Communicate(line, voice, rate='-5%').save(str(destination))


def soundtrack(directory, lines, language, scenes=None):
    rate, duration = 48000, len(lines) * SCENE_SECONDS
    output = np.zeros(rate*duration, dtype=np.float32)
    voice = 'hi-IN-SwaraNeural' if language == 'hi' else 'en-US-AnaNeural'
    for index, line in enumerate(lines):
        cache_key = hashlib.sha256((voice + '\0' + line).encode('utf-8')).hexdigest()[:20]
        with av.open(str(directory / f'{cache_key}.mp3')) as container:
            resampler = av.AudioResampler(format='fltp', layout='mono', rate=rate)
            pieces = []
            for frame in container.decode(audio=0):
                pieces.extend(f.to_ndarray().reshape(-1) for f in resampler.resample(frame))
            pieces.extend(f.to_ndarray().reshape(-1) for f in resampler.resample(None))
        samples = np.concatenate(pieces)
        if len(samples) / rate > SCENE_SECONDS - .3:
            raise RuntimeError(f'Narration line {index+1} is too long for its scene')
        start = int((index*SCENE_SECONDS+.25)*rate)
        output[start:start+len(samples)] += samples * .85
    # Original soft pentatonic bell accompaniment; no third-party recording or melody.
    notes = [523.25, 659.25, 783.99, 659.25, 587.33, 523.25, 783.99, 1046.5]
    for index in range(duration*2):
        start = int(index*.5*rate)
        t = np.arange(min(int(rate*.8), len(output)-start), dtype=np.float32)/rate
        frequency = notes[index % len(notes)]
        bell = (np.sin(math.tau*frequency*t) + .22*np.sin(math.tau*frequency*2*t)) * np.exp(-t*8)
        output[start:start+len(t)] += bell * .035
    # Short original cues repeat with the action and stay under the spoken lines.
    if scenes:
        for index, scene in enumerate(scenes):
            action = scene['action']
            cues = [(1.2,220),(3.1,247)] if action in ('play','celebrate') else [(2.0,784),(2.2,1047)] if action == 'find' else []
            for offset, frequency in cues:
                start = int((index*SCENE_SECONDS+offset)*rate)
                t = np.arange(int(rate*.16), dtype=np.float32)/rate
                output[start:start+len(t)] += np.sin(math.tau*(frequency*t-100*t*t))*np.exp(-t*24)*.05
    fade = np.minimum(1, np.arange(len(output))/int(rate*.25)) * np.minimum(1, np.arange(len(output))[::-1]/int(rate*.6))
    return np.clip(output*fade, -.95, .95).astype(np.float32)


def render(destination, width, height, audio, scenes, title, language, start_scene=0, scene_count=None):
    stage = Stage(width, height, language)
    scene_count = len(scenes) if scene_count is None else scene_count
    start_seconds = start_scene * SCENE_SECONDS
    duration = scene_count * SCENE_SECONDS
    with av.open(str(destination), 'w') as output:
        video = output.add_stream('libx264', rate=FPS)
        video.width, video.height, video.pix_fmt = width, height, 'yuv420p'
        video.options = {'crf':'21', 'preset':'fast'}
        sound = output.add_stream('aac', rate=48000)
        sound.layout = 'mono'
        sound.bit_rate = 96000
        sample_cursor = 0
        for index in range(duration*FPS):
            frame = av.VideoFrame.from_image(stage.render(start_seconds + index/FPS, scenes, title, index/FPS))
            frame.pts = index
            for packet in video.encode(frame): output.mux(packet)
            audio_start = round(start_seconds*48000) + sample_cursor
            audio_end = min(duration*48000, round((index+1)*48000/FPS))
            chunk = np.ascontiguousarray(audio[audio_start:round(start_seconds*48000)+audio_end].reshape(1,-1))
            af = av.AudioFrame.from_ndarray(chunk, format='fltp', layout='mono')
            af.sample_rate, af.pts = 48000, sample_cursor
            for packet in sound.encode(af): output.mux(packet)
            sample_cursor = audio_end
            if index % (FPS*SCENE_SECONDS) == 0: print(f'{destination.name}: scene {index//(FPS*SCENE_SECONDS)+1}/{scene_count}', flush=True)
        for packet in video.encode(): output.mux(packet)
        for packet in sound.encode(): output.mux(packet)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--speech-cache', type=Path, default=Path('work/cartoon-speech'))
    parser.add_argument('--story-json', type=Path, help='24–60 scene original story JSON')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.speech_cache.mkdir(parents=True, exist_ok=True)
    if args.story_json:
        story = load_story(args.story_json)
        scenes = story['scenes']
        language = story.get('language', 'en')
        lines = [scene['line'] for scene in scenes]
        title = story['title']
        asyncio.run(speech(args.speech_cache, lines, language))
        audio = soundtrack(args.speech_cache, lines, language, scenes)
        render(args.output/'episode-youtube.mp4', 1280,720,audio,scenes,title,language)
        scores = {'idle': 0, 'walk': 1, 'search': 2, 'find': 4, 'return': 3, 'play': 2, 'celebrate': 4}
        start = max(range(len(scenes)-3), key=lambda i: sum(scores[scene['action']] for scene in scenes[i:i+4]))
        render(args.output/'highlight-short.mp4', 720,1280,audio,scenes,title,language,start,4)
        Stage(1280,720,language).render(start*SCENE_SECONDS,scenes,title,0).save(args.output/'episode-poster.jpg')
        (args.output/'episode-notes.json').write_text(json.dumps({
            'title':title, 'duration_seconds':len(scenes)*SCENE_SECONDS,
            'highlight_start_scene':start+1, 'highlight_duration_seconds':20,
            'format':'Original 2D puppet animation from reusable illustrated characters; not full 3D or text-to-video generation',
            'language':language, 'narration':lines,
            'music':'Original synthesized pentatonic bell accompaniment',
            'status':'Manual story input; daily story generation and publishing remain disabled'
        },indent=2,ensure_ascii=False),encoding='utf-8')
        return
    pilot_actions = ['play', 'walk', 'search', 'find', 'return', 'play']
    scenes = [{'line':line,'action':pilot_actions[index]} for index,line in enumerate(LINES)]
    asyncio.run(speech(args.speech_cache, LINES, 'en'))
    audio = soundtrack(args.speech_cache, LINES, 'en', scenes)
    render(args.output/'milo-and-pip-pilot-landscape.mp4',1280,720,audio,scenes,'The Lost Ball','en')
    render(args.output/'milo-and-pip-pilot-vertical.mp4',720,1280,audio,scenes,'The Lost Ball','en')
    Stage(1280,720).render(18).save(args.output/'milo-and-pip-poster.jpg')
    (args.output/'cartoon-pilot-notes.json').write_text(json.dumps({
        'title':'Milo & Pip: The Lost Ball', 'duration_seconds':len(LINES)*SCENE_SECONDS,
        'format':'Original generated artwork with 2D puppet motion, not full 3D character animation',
        'narration':LINES, 'music':'Original synthesized pentatonic bell accompaniment',
        'status':'Local style pilot; daily generation and automatic publishing remain disabled'
    }, indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
