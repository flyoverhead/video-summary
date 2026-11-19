#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DRAFT_NAME, FINAL_NAME, defaults, manifest_path, read_json, run  # noqa: E402
from filters import scale_frame  # noqa: E402
from sample import _run_hw  # noqa: E402

DURATION_TOLERANCE_S = 5.0
TRIM_TOLERANCE_S = 0.1
PROJECT_FILES = ('config.json', 'clips.json', 'probe.json')
JOIN_DRIFT_S = 0.15
JOIN_DRIFT_MEASURED_S = 0.05


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


def report(project: Path, draft: bool = False, qa: bool = True) -> tuple[list[str], bool]:
    try:
        lines = _facts(Path(project), draft)
        problems = verify(project, draft=draft)
    except (KeyError, TypeError, ValueError, AttributeError, OSError, subprocess.CalledProcessError) as exc:
        lines, problems = [], [f'cannot check {project}: {type(exc).__name__}: {exc}']
    lines += [f'PROBLEM: {p}' for p in problems] or ['OK']
    if qa and not any(p.startswith(('output missing', 'render manifest missing', 'cannot check'))
                      for p in problems):
        lines += _qa_lines(Path(project), draft)
    return lines, not problems


def _qa_lines(project: Path, draft: bool) -> list[str]:
    try:
        config = read_json(Path(project) / 'config.json')
        manifest = read_json(manifest_path(config, draft))
        total = manifest_total(manifest)
        parsed = parse_qa(qa_scan(output_file(config, draft), defaults()['qa']), total)
        return qa_warnings(parsed, manifest, defaults()['qa'])
    except (KeyError, TypeError, ValueError, AttributeError, OSError, subprocess.CalledProcessError) as exc:
        return [f'WARN: QA scan failed: {type(exc).__name__}: {exc}']


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

    path = manifest_path(config, draft)
    if not path.exists():
        return [f'render manifest missing: {path}']
    manifest = read_json(path)
    span = manifest.get('range')
    if span:
        lo, hi = span
        if not 1 <= lo <= hi <= len(clips):
            return [f'manifest range {lo}-{hi} is outside clips.json (1-{len(clips)})']
        clips = clips[lo - 1:hi]

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

    entries = manifest['clips']
    if [m['file'] for m in entries] != [c['file'] for c in clips]:
        problems.append('manifest file list differs from clips.json')
    elif [bool(m['lut']) for m in entries] != [bool(c['lut']) for c in clips]:
        problems.append('manifest LUT flags differ from clips.json')
    return problems


TIME_FORMS = (r'\d+(?:\.\d+)?', r'\d+:[0-5]\d(?:\.\d+)?', r'\d+:[0-5]\d:[0-5]\d(?:\.\d+)?')


def parse_time(text: str) -> float:
    colons = text.count(':')
    if colons > 2 or not re.fullmatch(TIME_FORMS[colons], text):
        raise ValueError(f'not a time: {text!r}')
    seconds = 0.0
    for part in text.split(':'):
        seconds = seconds * 60 + float(part)
    return seconds


def format_clock(t: float, with_fraction: bool) -> str:
    tenths = round(t * 10)
    whole, frac = divmod(tenths, 10)
    hours, rest = divmod(whole, 3600)
    minutes, seconds = divmod(rest, 60)
    text = f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes}:{seconds:02d}'
    return f'{text}.{frac}' if with_fraction else text


def clip_length(clip: dict) -> float:
    # concat advances by each intermediate's container length (longest stream), not the plan
    return clip.get('out_duration', clip['duration'])


def manifest_total(manifest: dict) -> float:
    return sum(clip_length(c) for c in manifest['clips'])


def locate(manifest: dict, t: float) -> dict | None:
    entries = manifest['clips']
    elapsed = 0.0
    for i, clip in enumerate(entries):
        end = elapsed + clip_length(clip)
        if elapsed <= t < end or (i == len(entries) - 1 and t == end):
            offset = t - elapsed
            return {'number': clip['index'] + 1, 'file': clip['file'], 'source_t': clip['start'] + offset,
                    'clip_start': clip['start'], 'clip_end': clip['start'] + clip['duration'],
                    'offset': offset, 'label': clip['label']}
        elapsed = end
    return None


def format_location(t: float, loc: dict) -> str:
    return (f'{format_clock(t, t % 1 != 0)} → #{loc["number"]} {loc["file"]} @ {loc["source_t"]:.1f}s '
            f'(clip {loc["clip_start"]:.1f}→{loc["clip_end"]:.1f}, '
            f'{format_clock(int(loc["offset"] + 1e-6), False)} into it) "{loc["label"]}"')


def locate_lines(manifest: dict, texts: list[str]) -> tuple[list[str], bool]:
    total = manifest_total(manifest)
    lines, ok = [], True
    for text in texts:
        try:
            t = parse_time(text)
        except ValueError:
            lines.append(f'{text} → ERROR: not a time')
            ok = False
            continue
        loc = locate(manifest, t)
        if loc is None:
            lines.append(f'{text} → past the end ({format_clock(total, False)})')
            ok = False
        else:
            lines.append(format_location(t, loc))
    return lines, ok


def qa_scan(path: Path, cfg: dict) -> str:
    video = (f'scale=320:-2,blackdetect=d={cfg["black_min_s"]}:pix_th={cfg["black_pix_th"]},'
             f'freezedetect=n={cfg["freeze_noise_db"]}dB:d={cfg["freeze_min_s"]},scdet=threshold={cfg["scdet_threshold"]}')
    audio = f'silencedetect=noise={cfg["silence_db"]}dB:d={cfg["silence_min_s"]},ebur128=peak=true:framelog=quiet'
    return _run_hw(['ffmpeg', '-hide_banner', '-nostats', '-v', 'info', '-i', str(path),
                    '-vf', video, '-af', audio, '-f', 'null', '-']).stderr


def _spans(log: str, start: str, end: str, close_at: float | None) -> list[tuple[float, float]]:
    starts = [float(m) for m in re.findall(start, log)]
    ends = [float(m) for m in re.findall(end, log)]
    spans = list(zip(starts, ends))
    if close_at is not None and len(starts) > len(ends):
        spans += [(t, close_at) for t in starts[len(ends):] if t < close_at]
    return spans


def parse_qa(log: str, end: float | None = None) -> dict:
    summary = log.rsplit('Summary:', 1)[1] if 'Summary:' in log else ''
    lufs = re.search(r'\bI:\s+(-?\d+(?:\.\d+)?) LUFS', summary)
    peak = re.search(r'\bPeak:\s+(-?\d+(?:\.\d+)?) dBFS', summary)
    return {
        'black': _spans(log, r'black_start:([\d.]+)', r'black_end:([\d.]+)', end),
        'freeze': _spans(log, r'freeze_start: ([\d.]+)', r'freeze_end: ([\d.]+)', end),
        'silence': _spans(log, r'silence_start: ([\d.]+)', r'silence_end: ([\d.]+)', end),
        'cuts': sorted(float(t) for t in re.findall(r'lavfi\.scd\.time:\s*([\d.]+)', log)),
        'lufs': float(lufs.group(1)) if lufs else None,
        'true_peak': float(peak.group(1)) if peak else None,
    }


def _where(manifest: dict, t: float) -> str:
    loc = locate(manifest, t)
    if loc is None:
        return ''
    return ' (' + format_location(t, loc).split(' → ', 1)[1].split(' (clip ', 1)[0] + ')'


def _flashes(cuts: list[float], manifest: dict, cfg: dict) -> list[tuple[float, float]]:
    joins, elapsed = [], 0.0
    for clip in manifest['clips'][:-1]:
        elapsed += clip_length(clip)
        joins.append(elapsed)
    drift = JOIN_DRIFT_MEASURED_S if all('out_duration' in c for c in manifest['clips']) else JOIN_DRIFT_S
    bounds = sorted([c for c in cuts if all(abs(c - j) > drift for j in joins)] + joins)
    return [(a, b - a) for a, b in zip(bounds, bounds[1:]) if b - a < cfg['min_shot_s']]


def qa_warnings(parsed: dict, manifest: dict, cfg: dict) -> list[str]:
    warnings = []
    for kind in ('black', 'freeze', 'silence'):
        for start, end in parsed[kind]:
            warnings.append(f'WARN: {kind} {format_clock(start, True)}–{format_clock(end, True)}'
                            f'{_where(manifest, start)}')
    for start, shot in _flashes(parsed['cuts'], manifest, cfg):
        warnings.append(f'WARN: flash {format_clock(start, True)} shot {shot:.2f}s{_where(manifest, start)}')
    low, high = cfg['lufs_range']
    if parsed['lufs'] is not None and not low <= parsed['lufs'] <= high:
        warnings.append(f'WARN: loudness {parsed["lufs"]:.1f} LUFS outside {low:g}…{high:g}')
    if parsed['true_peak'] is not None and parsed['true_peak'] > cfg['true_peak_max']:
        warnings.append(f'WARN: true peak {parsed["true_peak"]:.1f} dBTP above {cfg["true_peak_max"]:.1f}')
    return warnings


def _locate_cli(project: Path, draft: bool, texts: list[str]) -> tuple[list[str], bool]:
    data, problems = _load(project, ('config.json',))
    if problems:
        return [f'ERROR: {p}' for p in problems], False
    path = manifest_path(data['config.json'], draft)
    if not path.exists():
        return [f'ERROR: render manifest missing: {path}'], False
    try:
        manifest = read_json(path)
    except (OSError, ValueError) as exc:
        return [f'ERROR: cannot read render manifest {path}: {exc}'], False
    return locate_lines(manifest, texts)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Check a rendered summary against its plan')
    parser.add_argument('project', type=Path)
    parser.add_argument('--draft', action='store_true')
    parser.add_argument('--no-qa', action='store_true')
    parser.add_argument('--locate', nargs='+', metavar='T',
                        help='output times to map to clips')
    raw = sys.argv[1:] if argv is None else argv
    # argparse takes '-1:00' for an option; mask it so negative clock times stay values
    masked = [f'\0{a}' if re.fullmatch(r'-[\d:.]+', a) else a for a in raw]
    args = parser.parse_args(masked)
    if args.locate:
        args.locate = [a.lstrip('\0') for a in args.locate]
    return args


def main() -> None:
    args = parse_args()
    if args.locate:
        lines, ok = _locate_cli(args.project, args.draft, args.locate)
        print('\n'.join(lines))
        sys.exit(0 if ok else 1)
    lines, ok = report(args.project, draft=args.draft, qa=not args.no_qa)
    print('\n'.join(lines))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
