#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DRAFT_NAME, FINAL_NAME, defaults, read_json, run  # noqa: E402
from filters import scale_frame  # noqa: E402

DURATION_TOLERANCE_S = 5.0
TRIM_TOLERANCE_S = 0.1
PROJECT_FILES = ('config.json', 'clips.json', 'probe.json')


def _load(project: Path, names: tuple[str, ...]) -> tuple[dict, list[str]]:
    data, problems = {}, []
    for name in names:
        path = Path(project) / name
        if not path.exists():
            problems.append(f'missing {name}')
            continue
        try:
            data[name] = read_json(path)
        except ValueError as exc:
            problems.append(f'invalid JSON in {name}: {exc}')
    return data, problems


CONFIG_KEYS = ('src', 'out', 'tmp', 'frame', 'quality')
CLIP_FIELDS = ('file', 'start', 'duration', 'label', 'lut')


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _probe_durations(probe) -> tuple[dict[str, float], list[str]]:
    if not isinstance(probe, dict) or not isinstance(probe.get('clips'), list):
        return {}, ['probe.json must be an object with a "clips" list']
    durations, problems = {}, []
    for i, clip in enumerate(probe['clips']):
        if not isinstance(clip, dict) or not isinstance(clip.get('file'), str) or not _num(clip.get('duration')):
            problems.append(f'probe.json clip {i} needs a "file" string and a numeric "duration"')
            continue
        durations[clip['file']] = float(clip['duration'])
    return durations, problems


def _config_problems(root: Path, config, durations: dict[str, float]) -> list[str]:
    if not isinstance(config, dict):
        return ['config.json must be an object']
    missing = [k for k in CONFIG_KEYS if k not in config]
    if missing:
        return [f'config.json missing {", ".join(missing)}']
    problems = []
    src, out, tmp = (Path(str(config[k])).expanduser().resolve() for k in ('src', 'out', 'tmp'))
    if src != root:
        problems.append(f'config.src is not the project root {root}: {config["src"]}')
    if out.parent != root:
        problems.append(f'config.out is not in the project root: {config["out"]}')
    if out.name != FINAL_NAME:
        problems.append(f'config.out must be named {FINAL_NAME} (draft: {DRAFT_NAME}): {config["out"]}')
    if any(out == (root / f).resolve() for f in durations):
        problems.append(f'config.out is a source clip listed in probe.json: {config["out"]}')
    if tmp == root or tmp.is_relative_to(root):
        problems.append(f'config.tmp must be outside the project folder: {config["tmp"]}')
    music = config.get('music')
    if music is not None:
        if not isinstance(music, dict) or not isinstance(music.get('file'), str):
            problems.append('config.music must be null or an object with a "file" path')
        elif not Path(music['file']).expanduser().is_file():
            problems.append(f'config.music file not found: {music["file"]}')
    return problems


def _clip_problems(root: Path, i: int, clip, durations: dict[str, float]) -> list[str]:
    if not isinstance(clip, dict):
        return [f'clip {i}: not an object']
    missing = [k for k in CLIP_FIELDS if k not in clip]
    if missing:
        return [f'clip {i}: missing fields {", ".join(missing)}']
    name, start, dur = clip['file'], clip['start'], clip['duration']
    if not isinstance(name, str) or not name:
        return [f'clip {i}: file must be a relative path string']
    if not (_num(start) and _num(dur) and start >= 0 and dur > 0):
        return [f'clip {i}: start must be a number >= 0 and duration a number > 0']
    problems = []
    if 'YYYYMMDD' in name:
        problems.append(f'clip {i}: template placeholder YYYYMMDD in {name}')
    if not (root / name).is_file():
        problems.append(f'clip {i}: file not found: {name}')
    elif name not in durations:
        problems.append(f'clip {i}: file not in probe.json: {name}')
    elif start + dur > durations[name] + TRIM_TOLERANCE_S:
        problems.append(f'clip {i}: {name} start+duration {start + dur:.2f}s '
                        f'exceeds source {durations[name]:.2f}s')
    return problems


def validate(project: Path, config, clips, probe) -> list[str]:
    root = Path(project).expanduser().resolve()
    durations, problems = _probe_durations(probe)
    problems += _config_problems(root, config, durations)
    if not isinstance(clips, list):
        return problems + ['clips.json must be a list']
    if not clips:
        return problems + ['clips.json is empty']
    for i, clip in enumerate(clips):
        problems += _clip_problems(root, i, clip, durations)
    return problems


def validate_project(project: Path) -> list[str]:
    data, problems = _load(project, PROJECT_FILES)
    if problems:
        return problems
    return validate(project, *(data[n] for n in PROJECT_FILES))


def _probe_output(path: Path) -> dict:
    info = json.loads(run(['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams',
                           '-show_format', str(path)]).stdout)
    video = next((s for s in info['streams'] if s['codec_type'] == 'video'), {})
    audio = next((s for s in info['streams'] if s['codec_type'] == 'audio'), None)
    return {'duration': float(info['format'].get('duration', 0)),
            'size': int(info['format'].get('size', 0)),
            'width': video.get('width'), 'height': video.get('height'),
            'audio_channels': audio['channels'] if audio else 0}


def probe_output(path: Path) -> dict:
    return _probe_output(Path(path))


def output_file(config: dict, draft: bool = False) -> Path:
    out = Path(config['out'])
    return out.parent / DRAFT_NAME if draft else out


def _facts(project: Path, draft: bool) -> list[str]:
    data, problems = _load(project, ('config.json',))
    if problems:
        return []
    out = output_file(data['config.json'], draft)
    lines = [f'Output:   {out}']
    if out.is_file() and out.stat().st_size:
        info = _probe_output(out)
        minutes, seconds = divmod(int(info['duration']), 60)
        lines += [f'Duration: {minutes}m {seconds:02d}s ({info["duration"]:.1f}s)',
                  f'Size:     {info["size"] / (1024 * 1024):.1f} MB']
    return lines


def report(project: Path, draft: bool = False) -> tuple[list[str], bool]:
    try:
        lines = _facts(Path(project), draft)
        problems = verify(project, draft=draft)
    except (KeyError, TypeError, ValueError, AttributeError, OSError, subprocess.CalledProcessError) as exc:
        lines, problems = [], [f'cannot check {project}: {type(exc).__name__}: {exc}']
    return lines + ([f'PROBLEM: {p}' for p in problems] or ['OK']), not problems


def verify(project: Path, draft: bool = False) -> list[str]:
    project = Path(project)
    data, problems = _load(project, ('config.json', 'clips.json'))
    if problems:
        return problems
    config, clips = data['config.json'], data['clips.json']
    out = output_file(config, draft)
    if not out.exists() or out.stat().st_size == 0:
        return [f'output missing or empty: {out}']
    info = _probe_output(out)

    planned = sum(c['duration'] for c in clips)
    if abs(info['duration'] - planned) > DURATION_TOLERANCE_S:
        problems.append(f'duration {info["duration"]:.1f}s differs from planned {planned:.1f}s')
    if info['audio_channels'] != 2:
        problems.append(f'audio has {info["audio_channels"]} channels, expected 2')

    frame = config['frame']
    if draft:
        frame = scale_frame(frame, config.get('draft_long_side', defaults()['render']['draft_long_side']))
    if (info['width'], info['height']) != (frame['width'], frame['height']):
        problems.append(f'dimensions {info["width"]}x{info["height"]} differ from expected '
                        f'{frame["width"]}x{frame["height"]}')

    manifest_path = Path(config['tmp']) / 'render-manifest.json'
    if not manifest_path.exists():
        problems.append(f'render manifest missing: {manifest_path}')
        return problems
    manifest = read_json(manifest_path)['clips']
    if [m['file'] for m in manifest] != [c['file'] for c in clips]:
        problems.append('manifest file list differs from clips.json')
    elif [bool(m['lut']) for m in manifest] != [bool(c['lut']) for c in clips]:
        problems.append('manifest LUT flags differ from clips.json')
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description='Check a rendered summary against its plan')
    parser.add_argument('project', type=Path)
    parser.add_argument('--draft', action='store_true')
    args = parser.parse_args()
    lines, ok = report(args.project, draft=args.draft)
    print('\n'.join(lines))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
