import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lut import escape_filter_path  # noqa: E402,F401

ASPECT_TOLERANCE = 0.01
NTSC_BASES = (24, 30, 48, 60, 120)


def escape_drawtext(text: str) -> str:
    for ch in ('\\', "'", ':', '%'):
        text = text.replace(ch, '\\' + ch)
    return text


def fps_expr(fps: float) -> str:
    for base in NTSC_BASES:
        if abs(fps - base * 1000 / 1001) < 0.005:
            return f'{base * 1000}/1001'
    return f'{fps:g}'


def even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


def scale_frame(frame: dict, long_side: int) -> dict:
    ratio = long_side / max(frame['width'], frame['height'])
    return {**frame, 'width': even(frame['width'] * ratio), 'height': even(frame['height'] * ratio)}


def drawtext(label: str, frame: dict, font: Path) -> str:
    h = frame['height']
    margin_x = max(1, round(h * 30 / 2560))
    margin_y = max(1, round(h * 60 / 2560))
    border = max(1, round(h * 12 / 2560))
    return (f'drawtext=fontfile={escape_filter_path(font)}'
            f':text={escape_filter_path(escape_drawtext(label))}'
            f':x={margin_x}:y=h-th-{margin_y}:fontsize={max(1, round(h / 50))}:fontcolor=white'
            f':box=1:boxcolor=black@0.55:boxborderw={border}')


def fit(src: dict, frame: dict) -> str:
    w, h = frame['width'], frame['height']
    target = w / h
    if abs(src['width'] / src['height'] - target) / target < ASPECT_TOLERANCE:
        return f'scale={w}:{h},setsar=1'
    return (f'split[a][b];'
            f'[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=20[bg];'
            f'[b]scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2[fg];'
            f'[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1')


def video_filter(clip: dict, src: dict, frame: dict, lut: Path | None, font: Path,
                 pix_fmt: str = 'yuv420p10le') -> str:
    chain = []
    if clip['lut']:
        if lut is None:
            raise ValueError(f'clip {clip["file"]} wants a LUT but none is configured')
        chain.append(f'lut3d=file={escape_filter_path(lut)}')
    chain.append(f'fps={fps_expr(frame["fps"])}')
    chain.append(fit(src, frame))
    chain.append(drawtext(clip['label'], frame, font))
    chain.append(f'format={pix_fmt}')
    return ','.join(chain)


def audio_filter(src: dict) -> str | None:
    if src.get('audio_channels', 0) < 1:
        return None
    # DJI alternates mono/stereo between clips and the right mic is noisy; keeping only the left
    # channel gives every intermediate the same layout, which concat needs to keep audio.
    return 'pan=mono|c0=c0,aresample=48000,apad'


def music_args(music: dict, video_s: float) -> list[str]:
    fade = f'afade=t=out:st={max(0.0, video_s - 2):.3f}:d=2'
    head = ['-stream_loop', '-1', '-i', str(music['file'])]
    tail = ['-t', f'{video_s:.3f}']
    if music['mode'] == 'replace':
        return head + ['-map', '0:v', '-map', '1:a', '-af', fade] + tail
    if music['mode'] == 'duck':
        stereo = 'aformat=sample_rates=48000:channel_layouts=stereo'
        graph = (f'[1:a]{stereo},volume={music.get("duck_db", -18)}dB,{fade}[m];'
                 f'[0:a]{stereo},asplit[key][cam];'
                 '[m][key]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=500[duck];'
                 '[cam][duck]amix=inputs=2:duration=first:normalize=0[mix]')
        return head + ['-filter_complex', graph, '-map', '0:v', '-map', '[mix]'] + tail
    raise ValueError(f'unknown music mode: {music["mode"]}')
