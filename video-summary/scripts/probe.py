#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import run, write_output  # noqa: E402

LONG_SIDE = 2560


def find_clips(root: Path) -> list[Path]:
    root = Path(root)
    return sorted(p for p in root.rglob('*')
                  if p.is_file() and p.suffix.lower() == '.mp4'
                  and not p.name.startswith('.')
                  and not re.fullmatch(r'SUMMARY_VIDEO.*\.mp4', p.name, re.IGNORECASE))


def _ffprobe(path: Path, stream: str) -> dict:
    out = run(['ffprobe', '-v', 'error', '-select_streams', stream, '-print_format', 'json',
               '-show_entries',
               'stream=codec_type,width,height,r_frame_rate,avg_frame_rate,channels:stream_tags=rotate:stream_side_data=rotation:format=duration:format_tags=creation_time',
               str(path)]).stdout
    return json.loads(out)


def _fraction(text: str) -> float:
    try:
        return float(Fraction(text))
    except (ValueError, ZeroDivisionError):
        return 0.0


def _mdls_created(path: Path) -> str | None:
    try:
        out = run(['mdls', '-raw', '-name', 'kMDItemContentCreationDate', str(path)]).stdout.strip()
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None
    if not out or out == '(null)':
        return None
    try:
        stamp = datetime.strptime(out, '%Y-%m-%d %H:%M:%S %z')
    except ValueError:
        return None
    return stamp.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _filename_created(path: Path) -> str | None:
    match = re.search(r'(?<!\d)(20\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?!\d)', Path(path).name)
    if not match:
        return None
    try:
        stamp = datetime(*map(int, match.groups()))
    except ValueError:
        return None
    return stamp.strftime('%Y-%m-%dT%H:%M:%SZ')


def _created(path: Path, tags: dict) -> str:
    stamp = tags.get('creation_time') or _mdls_created(path) or _filename_created(path)
    if stamp:
        return stamp
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return mtime.strftime('%Y-%m-%dT%H:%M:%SZ')


def _rotation(stream: dict) -> int:
    values = [stream.get('tags', {}).get('rotate')]
    values += [sd.get('rotation') for sd in stream.get('side_data_list', [])]
    for value in values:
        if value is not None:
            try:
                return int(float(value)) % 360
            except ValueError:
                continue
    return 0


def probe_clip(root: Path, path: Path) -> dict:
    try:
        video = _ffprobe(path, 'v:0')
    except subprocess.CalledProcessError as exc:
        raise ValueError(f'ffprobe failed: {(exc.stderr or "").strip()}') from exc
    streams = video.get('streams') or []
    if not streams:
        raise ValueError(f'no video stream: {path}')
    v = streams[0]
    fps = _fraction(v.get('r_frame_rate', '0/1')) or _fraction(v.get('avg_frame_rate', '0/1'))
    width, height = int(v['width']), int(v['height'])
    if _rotation(v) in (90, 270):
        width, height = height, width
    audio = (_ffprobe(path, 'a:0').get('streams') or [{}])[0]
    fmt = video.get('format', {})
    return {
        'file': str(Path(path).relative_to(root)),
        'duration': float(fmt.get('duration', 0.0)),
        'fps': round(fps, 3),
        'width': width,
        'height': height,
        'audio_channels': int(audio.get('channels', 0)),
        'created': _created(Path(path), fmt.get('tags', {})),
    }


def _shape(clip: dict) -> str:
    w, h = clip['width'], clip['height']
    if abs(w / h - 1) < 0.05:
        return 'square'
    return 'wide' if w > h else 'vertical'


def _even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


def _majority(values: list, prefer_high: bool = False):
    counts = Counter(values)
    top = max(counts.values())
    tied = [v for v in counts if counts[v] == top]
    return max(tied) if prefer_high else tied[0]


def choose_frame(clips: list[dict], long_side: int = LONG_SIDE) -> dict:
    shape = _majority([_shape(c) for c in clips])
    rates = [c['fps'] for c in clips if c['fps'] > 0]
    if not rates:
        raise ValueError('no clip has a valid frame rate')
    fps = _majority(rates, prefer_high=True)
    if shape == 'square':
        return {'shape': shape, 'width': long_side, 'height': long_side, 'fps': fps}
    members = [c for c in clips if _shape(c) == shape]
    best = _majority([(c['width'], c['height']) for c in members])
    short = _even(long_side * min(best) / max(best))
    width, height = (long_side, short) if shape == 'wide' else (short, long_side)
    return {'shape': shape, 'width': width, 'height': height, 'fps': fps}


def collect_probe(root: Path) -> dict:
    root = Path(root)
    clips = []
    for path in find_clips(root):
        try:
            clips.append(probe_clip(root, path))
        except ValueError as exc:
            print(f'skipping {path}: {exc}', file=sys.stderr)
    if not clips:
        raise SystemExit(f'no .mp4 clips under {root}')
    clips.sort(key=lambda c: (c['created'], c['file']))
    return {'clips': clips, 'frame': choose_frame(clips)}


def probe_project(root: Path, overwrite: bool = False) -> dict:
    data = collect_probe(root)
    write_output(Path(root), 'probe.json', data, overwrite=overwrite)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description='Probe clips and choose the output frame')
    parser.add_argument('project')
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    try:
        data = probe_project(Path(args.project).expanduser(), overwrite=args.overwrite)
    except FileExistsError as exc:
        raise SystemExit(f'exists, use --overwrite: {exc}')
    print(f'{"file":<40} {"dur":>7} {"fps":>6} {"size":>10} {"aud":>3}  created')
    for c in data['clips']:
        print(f'{c["file"]:<40} {c["duration"]:>7.1f} {c["fps"]:>6.2f} '
              f'{c["width"]}x{c["height"]:<5} {c["audio_channels"]:>3}  {c["created"]}')
    f = data['frame']
    print(f'frame: {f["shape"]} {f["width"]}x{f["height"]} @ {f["fps"]} fps')


if __name__ == '__main__':
    main()
