"""Small, original Fit-zee graphics and font checks; no external assets."""
from pathlib import Path
import textwrap


def caption_font(language, directory=Path('/usr/share/fonts')):
    name = 'NotoSansDevanagari-Bold.ttf' if language == 'hi' else 'NotoSans-Bold.ttf'
    return next(Path(directory).rglob(name))


def check_glyphs(font_path, text):
    from PIL import ImageFont
    font = ImageFont.truetype(str(font_path), 48)
    missing = bytes(font.getmask('\U0010ffff'))
    if any(bytes(font.getmask(char)) == missing for char in set(text) if not char.isspace()):
        raise RuntimeError('Caption font does not cover the script; refusing square-box subtitles')


def background_card(meta, destination):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (720, 1280), '#101827')
    draw = ImageDraw.Draw(image)
    latin = ImageFont.truetype(str(caption_font('en')), 36)
    title_font = ImageFont.truetype(str(caption_font(meta['language'])), 58)
    check_glyphs(caption_font(meta['language']), meta['title'])
    draw.rounded_rectangle((48, 58, 278, 120), radius=20, fill='#a3ff6a')
    draw.text((72, 63), 'FIT-ZEE', font=latin, fill='#101827')
    draw.text((52, 185), 'ONE SMALL HABIT.', font=latin, fill='#a3ff6a')
    for index, line in enumerate(textwrap.wrap(meta['title'], width=19)[:5]):
        draw.text((50, 290 + index * 86), line, font=title_font, fill='white')
    draw.line((52, 770, 668, 770), fill='#a3ff6a', width=6)
    draw.text((52, 1180), 'MOVE. LEARN. REPEAT.', font=latin, fill='#a3ff6a')
    image.save(destination)
