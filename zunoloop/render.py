"""Neural narration with word-synchronized subtitles for Agnes motion."""
import asyncio
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
import edge_tts

PROFILE = 'neural-word-fullframe-v2'
VOICES = {'id': 'id-ID-ArdiNeural', 'en': 'en-US-GuyNeural'}

def duration(path):
    return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)], text=True))

def stamp(seconds):
    centis = round(seconds * 100)
    return f'{centis//360000}:{centis//6000%60:02}:{centis//100%60:02}.{centis%100:02}'

def write_subtitles(metadata, target, limit):
    events = [json.loads(line) for line in Path(metadata).read_text().splitlines()]
    cues = [e for e in events if e['type'] == 'WordBoundary']
    if not cues:
        raise RuntimeError('Speech service did not return word timestamps')
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,DejaVu Sans,58,&H00FFFFFF,&H00FFFFFF,&H00101820,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,35,35,235,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    lines = []
    previous = 0
    for cue in cues:
        start = cue['offset']/10_000_000
        end = (cue['offset']+cue['duration'])/10_000_000
        if start < previous - .03 or end > limit + .03:
            raise RuntimeError('Invalid word alignment or truncated narration')
        words = cue['text'].split()
        # Some locales report several tokens in one boundary; display each alone.
        for i, word in enumerate(words):
            left = start + (end-start)*i/len(words)
            right = start + (end-start)*(i+1)/len(words)
            safe = word.replace('\\','').replace('{','').replace('}','')
            lines.append(f'Dialogue: 0,{stamp(left)},{stamp(right)},Word,,0,0,0,,{safe}\n')
        previous = end
    Path(target).write_text(header+''.join(lines))
    return len(lines)

def finish_video(source, story, language, output, legacy=False):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('ffmpeg and ffprobe required')
    length = duration(source)
    if not 7 <= length <= 9:
        raise RuntimeError('Agnes source must be 7–9 seconds')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        audio, metadata, subtitles = [Path(tmp)/n for n in ('voice.mp3','words.jsonl','words.ass')]
        for rate in ('+0%', '+10%', '+20%', '+30%'):
            asyncio.run(edge_tts.Communicate(story['voice'], VOICES[language], rate=rate,
                        boundary='WordBoundary').save(str(audio), str(metadata)))
            if duration(audio) <= length - .05:
                break
        else:
            raise RuntimeError('Narration too long; shorten script rather than cut audio')
        count = write_subtitles(metadata, subtitles, length)
        # Legacy exports have captions burned below y=870. Remove that region,
        # then fill the entire 9:16 canvas with the remaining original motion.
        if legacy:
            vf = f'[0:v]crop=iw:trunc(ih*0.67/2)*2:0:0,scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,ass={subtitles}[v]'
        else:
            vf = f'[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,ass={subtitles}[v]'
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-i',str(audio),
                        '-filter_complex',vf,'-map','[v]','-map','1:a','-af','apad','-t',str(length),
                        '-r','24','-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p',
                        '-c:a','aac','-movflags','+faststart',str(output)],check=True,capture_output=True)
        shutil.copy(metadata, output.with_suffix('.words.jsonl'))
        shutil.copy(subtitles, output.with_suffix('.ass'))
        print(f'Neural voice {VOICES[language]}, rate {rate}, {count} individual word subtitles',flush=True)
    if output.stat().st_size < 30_000:
        raise RuntimeError('Finished video unexpectedly small')

def reframe_existing(source, narrated, output):
    """Remove legacy burned captions and retain verified neural audio/timings."""
    source, narrated, output = map(Path, (source, narrated, output))
    subtitles = narrated.with_suffix('.ass')
    metadata = narrated.with_suffix('.words.jsonl')
    if not subtitles.is_file() or not metadata.is_file():
        raise RuntimeError('Verified neural subtitle timing files are required')
    length = duration(source)
    if not 7 <= length <= 9:
        raise RuntimeError('Invalid original Agnes duration')
    vf = f'[0:v]crop=iw:trunc(ih*0.67/2)*2:0:0,scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,ass={subtitles.resolve()}[v]'
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-i',str(narrated),
                    '-filter_complex',vf,'-map','[v]','-map','1:a','-t',str(length),
                    '-r','24','-c:v','libx264','-preset','veryfast','-crf','24',
                    '-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',str(output)],
                   check=True,capture_output=True)
    shutil.copy(subtitles, output.with_suffix('.ass'))
    shutil.copy(metadata, output.with_suffix('.words.jsonl'))
    print(f'Full-frame 720x1280; preserved neural audio and word timings: {output.name}',flush=True)
