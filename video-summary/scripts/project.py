#!/usr/bin/env python3
import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import defaults, output_path, read_json, write_output  # noqa: E402
from probe import _shape  # noqa: E402

JSON_NAMES = ('brief.json', 'clips.json', 'config.json')
TEXT_NAMES = ('SUMMARY.md',)
FINAL_SPEED = 0.25


def _prepare(name: str, raw: str) -> tuple[object, str]:
    if name in TEXT_NAMES:
        return raw, raw
    if name not in JSON_NAMES:
        raise ValueError(f'not writable here: {name} (allowed: {", ".join(JSON_NAMES + TEXT_NAMES)})')
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f'invalid JSON for {name}: {exc}') from exc
    return data, json.dumps(data, indent=2, ensure_ascii=False) + '\n'


def write(project: Path, name: str, raw: str, overwrite: bool = False) -> tuple[str, str]:
    data, text = _prepare(name, raw)
    path = output_path(Path(project), name)
    old = path.read_text() if path.exists() else None
    if old == text:
        return 'unchanged', ''
    diff = '' if old is None else ''.join(difflib.unified_diff(
        old.splitlines(True), text.splitlines(True), f'a/{name}', f'b/{name}'))
    if old is not None and not overwrite:
        return 'refused', diff
    write_output(Path(project), name, data, overwrite=old is not None)
    return ('created' if old is None else 'overwritten'), diff


def _quality_name(value: int) -> str:
    presets = defaults()['render']['quality']
    return next((name for name, q in presets.items() if q == value), 'custom')


def _mmss(seconds: float) -> str:
    seconds = round(seconds)
    return f'{seconds // 60}m {seconds % 60:02d}s'


def _fitted(project: Path, clips: list[dict], shape: str) -> str:
    shapes = {c['file']: _shape(c) for c in read_json(project / 'probe.json')['clips']}
    odd = sorted({f'{c["file"]} {shapes[c["file"]]}' for c in clips
                  if c['file'] in shapes and shapes[c['file']] != shape})
    if not odd:
        return 'none'
    return f'{len(odd)} clip{"s" if len(odd) > 1 else ""} with blurred fill ({", ".join(odd)})'


def summary(project: Path) -> str:
    project = Path(project)
    brief = read_json(project / 'brief.json')
    config = read_json(project / 'config.json')
    clips = read_json(project / 'clips.json')
    total = sum(float(c['duration']) for c in clips)
    lut_files = sorted({c['file'] for c in clips if c.get('lut')})
    lut_clips = sum(1 for c in clips if c.get('lut'))
    frame = config['frame']
    music = config.get('music')
    quality = int(config['quality'])
    out = Path(config['out'])
    if out.exists():
        out_note = f'{out}  (exists, {out.stat().st_size / 1e6:.1f} MB; final needs --overwrite)'
    else:
        out_note = str(out)
    lines = [
        ('Type', brief.get('type', 'trip')),
        ('Clips', f'{len(clips)} clips'),
        ('Duration', f'{_mmss(total)} (target {"-".join(map(str, brief.get("target_min", [])))} min)'),
        ('Frame', f'{frame["shape"]} {frame["width"]}x{frame["height"]} @ {frame["fps"]:g} fps'),
        ('LUT', f'{lut_clips} of {len(clips)}' + (f' ({", ".join(lut_files)})' if lut_files else '')),
        *([('Fitted', _fitted(project, clips, frame['shape']))] if (project / 'probe.json').exists() else []),
        ('Music', f'{music["mode"]} ({music["file"]})' if music else 'none'),
        ('Quality', f'{_quality_name(quality)} ({quality})'),
        ('Output', out_note),
        ('Estimate', f'~{_mmss(total / FINAL_SPEED)} final at {FINAL_SPEED:g}x realtime'),
    ]
    return '\n'.join(f'{k + ":":<10} {v}' for k, v in lines) + '\n'


def main() -> None:
    parser = argparse.ArgumentParser(description='Write allowlisted project files and show the render summary')
    sub = parser.add_subparsers(dest='cmd', required=True)
    wr = sub.add_parser('write', help='write brief.json, clips.json, config.json or SUMMARY.md')
    wr.add_argument('project')
    wr.add_argument('name')
    wr.add_argument('src', help='source file, or - for stdin')
    wr.add_argument('--overwrite', action='store_true')
    sm = sub.add_parser('summary', help='print the pre-render summary')
    sm.add_argument('project')
    args = parser.parse_args()
    root = Path(args.project).expanduser()
    if not root.is_dir():
        print(f'ERROR: project folder not found: {root}', file=sys.stderr)
        sys.exit(2)
    try:
        if args.cmd == 'summary':
            print(summary(root), end='')
            return
        raw = sys.stdin.read() if args.src == '-' else Path(args.src).expanduser().read_text()
        status, diff = write(root, args.name, raw, overwrite=args.overwrite)
    except (OSError, ValueError, KeyError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(2)
    if diff:
        print(diff, end='' if diff.endswith('\n') else '\n')
    if status == 'refused':
        print(f'{args.name} exists and differs; show the diff, ask, then re-run with --overwrite',
              file=sys.stderr)
        sys.exit(1)
    print(f'{status}: {root / args.name}')


if __name__ == '__main__':
    main()
