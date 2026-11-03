"""Original reusable-art cartoon pilot. CPU rendering; no paid generation API.

Run: python cartoon_pilot.py --output DIRECTORY
Dependencies: Pillow, numpy, av, edge-tts. This is a style pilot, not the daily publisher.
"""
import argparse
import asyncio
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


def story_state(seconds):
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


def font_path():
    candidates = [Path('C:/Windows/Fonts/arialbd.ttf'), Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')]
    return next(path for path in candidates if path.exists())


class Stage:
    def __init__(self, width, height):
        self.width, self.height = width, height
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
        self.caption_font = ImageFont.truetype(str(font_path()), 30 if self.portrait else 29)
        self.small_font = ImageFont.truetype(str(font_path()), 20)
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

    def render(self, seconds):
        state = story_state(seconds)
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
        hop = max(0, math.sin(seconds * 4.2)) * (13 if scene in (0, 5) else 3)
        bird_lift = (18 + 12 * math.sin(seconds * 6)) if scene in (2, 3) else max(0, math.sin(seconds * 5))*8
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
            zoom, focus = [(1.0,.5),(1.12,.68),(1.36,.29),(1.25,.7),(1.08,.48),(1.0,.5)][scene]
            zoom += .025 * smooth(phase)
            crop_w, crop_h = w/zoom, h/zoom
            left = max(0,min(w-crop_w,w*focus-crop_w/2))
            top = max(0,min(h-crop_h,h*.54-crop_h/2))
            frame = frame.crop((round(left),round(top),round(left+crop_w),round(top+crop_h))).resize((w,h),Image.Resampling.LANCZOS)
        # A title identifies the pilot; captions remain short and visually safe.
        if seconds < 3.8:
            title_font = ImageFont.truetype(str(font_path()), 30 if self.portrait else 35)
            self.center_text(frame, 'MILO & PIP', h*.06, title_font, '#fff4cf', '#31585b')
            self.center_text(frame, 'The Lost Ball', h*.06+48, self.small_font, '#ffffff', '#31585b')
        caption = LINES[scene]
        words = caption.split()
        lines = [' '.join(words[:len(words)//2]), ' '.join(words[len(words)//2:])] if self.portrait and len(caption) > 27 else [caption]
        caption_y = h * (0.87 if self.portrait else 0.905)
        overlay = Image.new('RGBA', frame.size)
        od = ImageDraw.Draw(overlay)
        widths = [od.textbbox((0,0), line, font=self.caption_font)[2] for line in lines]
        box_w = min(w-30, max(widths)+44)
        od.rounded_rectangle(((w-box_w)/2, caption_y-12, (w+box_w)/2, caption_y+len(lines)*38+8), radius=18, fill=(20, 45, 50, 195))
        frame.alpha_composite(overlay)
        for index, line in enumerate(lines):
            self.center_text(frame, line, caption_y+index*38, self.caption_font, '#ffffff')
        if scene == 5 and phase > .2:
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


async def speech(directory):
    import edge_tts
    for index, line in enumerate(LINES):
        destination = directory / f'line-{index}.mp3'
        if not destination.exists():
            await edge_tts.Communicate(line, 'en-US-AnaNeural', rate='-5%').save(str(destination))


def soundtrack(directory):
    rate, duration = 48000, len(LINES) * SCENE_SECONDS
    output = np.zeros(rate*duration, dtype=np.float32)
    for index in range(len(LINES)):
        with av.open(str(directory / f'line-{index}.mp3')) as container:
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
    # Gentle bounce tones follow the ball; a two-note discovery chime at scene four.
    for seconds, frequency in [(1.2,220),(2.5,220),(5.7,196),(15.4,784),(15.65,1047),(26.2,220),(27.5,220)]:
        start = int(seconds*rate)
        t = np.arange(int(rate*.16), dtype=np.float32)/rate
        output[start:start+len(t)] += np.sin(math.tau*(frequency*t-100*t*t))*np.exp(-t*24)*.07
    fade = np.minimum(1, np.arange(len(output))/int(rate*.25)) * np.minimum(1, np.arange(len(output))[::-1]/int(rate*.6))
    return np.clip(output*fade, -.95, .95).astype(np.float32)


def render(destination, width, height, audio):
    stage = Stage(width,height)
    with av.open(str(destination), 'w') as output:
        video = output.add_stream('libx264', rate=FPS)
        video.width, video.height, video.pix_fmt = width, height, 'yuv420p'
        video.options = {'crf':'21', 'preset':'fast'}
        sound = output.add_stream('aac', rate=48000)
        sound.layout = 'mono'
        sound.bit_rate = 96000
        sample_cursor = 0
        for index in range(len(LINES)*SCENE_SECONDS*FPS):
            frame = av.VideoFrame.from_image(stage.render(index/FPS))
            frame.pts = index
            for packet in video.encode(frame): output.mux(packet)
            audio_end = min(len(audio), round((index+1)*48000/FPS))
            chunk = np.ascontiguousarray(audio[sample_cursor:audio_end].reshape(1,-1))
            af = av.AudioFrame.from_ndarray(chunk, format='fltp', layout='mono')
            af.sample_rate, af.pts = 48000, sample_cursor
            for packet in sound.encode(af): output.mux(packet)
            sample_cursor = audio_end
            if index % (FPS*SCENE_SECONDS) == 0: print(f'{destination.name}: scene {index//(FPS*SCENE_SECONDS)+1}/6', flush=True)
        for packet in video.encode(): output.mux(packet)
        for packet in sound.encode(): output.mux(packet)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--speech-cache', type=Path, default=Path('work/cartoon-speech'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.speech_cache.mkdir(parents=True, exist_ok=True)
    asyncio.run(speech(args.speech_cache))
    audio = soundtrack(args.speech_cache)
    render(args.output/'milo-and-pip-pilot-landscape.mp4', 1280,720,audio)
    render(args.output/'milo-and-pip-pilot-vertical.mp4', 720,1280,audio)
    Stage(1280,720).render(18).save(args.output/'milo-and-pip-poster.jpg')
    (args.output/'cartoon-pilot-notes.json').write_text(json.dumps({
        'title':'Milo & Pip: The Lost Ball', 'duration_seconds':len(LINES)*SCENE_SECONDS,
        'format':'Original generated artwork with 2D puppet motion, not full 3D character animation',
        'narration':LINES, 'music':'Original synthesized pentatonic bell accompaniment',
        'status':'Local style pilot; daily generation and automatic publishing remain disabled'
    }, indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
