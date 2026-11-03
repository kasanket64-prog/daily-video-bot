"""Inspect the actual pilot exports, including scene continuity and caption layout."""
import json
import sys
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw
from cartoon_pilot import Stage, story_state, LINES, SCENE_SECONDS, FPS


def verify(directory):
    assert not story_state(SCENE_SECONDS*1.99)['ball_visible']
    assert not story_state(SCENE_SECONDS*2.5)['ball_visible']
    assert story_state(SCENE_SECONDS*3.5)['ball_visible']
    for boundary in (SCENE_SECONDS*3, SCENE_SECONDS*4, SCENE_SECONDS*5):
        assert abs(story_state(boundary-.001)['bird'] - story_state(boundary)['bird']) < .001
    reports = []
    for name, width, height in [('landscape',1280,720), ('vertical',720,1280)]:
        stage = Stage(width,height)
        assert np.mean(np.abs(np.asarray(stage.render(1)).astype(float)-np.asarray(stage.render(1.3)).astype(float))) > .2
        draw = ImageDraw.Draw(Image.new('RGB',(width,height)))
        for line in LINES:
            words = line.split()
            lines = [' '.join(words[:len(words)//2]), ' '.join(words[len(words)//2:])] if stage.portrait and len(line)>27 else [line]
            assert all(draw.textbbox((0,0),text,font=stage.caption_font)[2] < width-50 for text in lines)
        path = directory / f'milo-and-pip-pilot-{name}.mp4'
        with av.open(str(path)) as container:
            assert abs(container.duration/1000000-len(LINES)*SCENE_SECONDS) < .1
            video = container.streams.video[0]
            assert (video.width,video.height)==(width,height)
            assert len(container.streams.audio)==1
            samples = {}
            frame_count = 0
            for frame in container.decode(video=0):
                if frame_count in [seconds*FPS for seconds in (1,7,12,17,22,27)]:
                    samples[frame_count]=frame.to_image()
                frame_count+=1
                last_time=frame.time
            assert frame_count==len(LINES)*SCENE_SECONDS*FPS
            assert last_time > len(LINES)*SCENE_SECONDS-.1
            thumb_w,thumb_h = (384,216) if name=='landscape' else (180,320)
            sheet = Image.new('RGB',(thumb_w*3,thumb_h*2))
            for index,seconds in enumerate((1,7,12,17,22,27)):
                im=samples[seconds*FPS].resize((thumb_w,thumb_h))
                sheet.paste(im,((index%3)*thumb_w,(index//3)*thumb_h))
            sheet.save(directory/f'{name}-checked-frames.jpg')
        with av.open(str(path)) as container:
            audio = np.concatenate([frame.to_ndarray().reshape(-1) for frame in container.decode(audio=0)])
            assert np.isfinite(audio).all()
            assert .001 < float(np.sqrt(np.mean(audio**2))) < .5
        reports.append({'file':path.name,'duration_seconds':30,'dimensions':[width,height],
                        'frames':frame_count,'audio_present':True,'caption_layout':'fits',
                        'motion_and_story_checks':'passed'})
    (directory/'export-checks.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    print(json.dumps(reports,indent=2))


if __name__=='__main__':
    verify(Path(sys.argv[1]))
