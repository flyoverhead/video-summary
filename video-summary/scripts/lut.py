#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import LUT_PATH, cache_dir, read_json, run, write_output  # noqa: E402

PREVIEW_SIDE_MAX = 960
FONTS = ('/System/Library/Fonts/Helvetica.ttc', '/System/Library/Fonts/Supplemental/Arial.ttf')


def escape_filter_path(path: str | Path) -> str:
    value = str(path)
    for ch in ('\\', "'", ':'):
        value = value.replace(ch, '\\' + ch)
    return re.sub(r"([\\',;\[\]])", r'\\\1', value)


def camera_source(streams: list[dict]) -> str:
    return 'dji' if any(st.get('codec_tag_string') == 'djmd' for st in streams) else 'other'


def _streams(path: Path) -> list[dict]:
    out = run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,codec_tag_string',
               '-of', 'json', str(path)]).stdout
    return json.loads(out).get('streams', [])


def detect(root: Path) -> dict[str, tuple[str, str]]:
    root = Path(root)
    return {c['file']: ('unknown', camera_source(_streams(root / c['file'])))
            for c in read_json(root / 'probe.json')['clips']}


def _label(text: str, x: str) -> str:
    font = next((f for f in FONTS if Path(f).exists()), None)
    fontfile = f'fontfile={escape_filter_path(font)}:' if font else ''
    return (f"drawtext={fontfile}text={text}:x={x}:y=h*0.03:fontsize=h*0.05:"
            'fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=8')


def preview(src: Path, t: float, out: Path, lut: Path = LUT_PATH) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    graph = (f"[0:v]scale='min({PREVIEW_SIDE_MAX},iw)':-2,split[a][b];"
             f"[a]{_label('BEFORE', '(w-text_w)/2')}[l];"
             f"[b]lut3d=file={escape_filter_path(lut)},{_label('AFTER', '(w-text_w)/2')}[r];"
             '[l][r]hstack')
    run(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-ss', f'{t:.3f}', '-i', str(src),
         '-frames:v', '1', '-filter_complex', graph, '-q:v', '3', str(out)])
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f'no preview frame at {t:.3f}s in {src}')
    return out


BOOLS = {'true': True, 'false': False}


def _bool(text: str) -> bool:
    if text.lower() not in BOOLS:
        raise ValueError(f'expected true or false, got {text!r}')
    return BOOLS[text.lower()]


def parse_decisions(items: list[str], all_value: bool | None, files: list[str]) -> dict[str, bool]:
    decisions = {f: all_value for f in files} if all_value is not None else {}
    for item in items:
        file, sep, value = item.rpartition('=')
        if not sep or not file:
            raise ValueError(f'expected FILE=true|false, got {item!r}')
        decisions[file] = _bool(value)
    if not decisions:
        raise ValueError('nothing to set: give FILE=true|false or --all true|false')
    return decisions


def set_decisions(root: Path, decisions: dict[str, bool]) -> list[str]:
    root = Path(root)
    known = {c['file'] for c in read_json(root / 'probe.json')['clips']}
    unknown = sorted(set(decisions) - known)
    if unknown:
        raise ValueError(f'not in probe.json: {", ".join(unknown)}')
    moments = read_json(root / 'moments.json')
    moments['lut'] = {**moments.get('lut', {}), **decisions}
    write_output(root, 'moments.json', moments, overwrite=True)
    changed = []
    clips_path = root / 'clips.json'
    if clips_path.exists():
        clips = read_json(clips_path)
        for i, clip in enumerate(clips):
            if clip['file'] in decisions and bool(clip.get('lut')) != decisions[clip['file']]:
                clip['lut'] = decisions[clip['file']]
                changed.append(f'clip {i} {clip["file"]}: lut {clip["lut"]}')
        if changed:
            write_output(root, 'clips.json', clips, overwrite=True)
    return changed


def show(root: Path) -> tuple[list[str], list[str]]:
    root = Path(root)
    files = [c['file'] for c in read_json(root / 'probe.json')['clips']]
    lut = read_json(root / 'moments.json').get('lut', {})
    lines = [f'{"on " if lut.get(f) else "off"}  {f}' for f in files]
    mismatches = []
    clips_path = root / 'clips.json'
    if clips_path.exists():
        for i, clip in enumerate(read_json(clips_path)):
            want = bool(lut.get(clip['file']))
            if bool(clip.get('lut')) != want:
                mismatches.append(f'clip {i} {clip["file"]}: clips.json lut {str(bool(clip.get("lut"))).lower()}, '
                                  f'moments.json {str(want).lower()}')
    return lines, mismatches


def _fail(exc: Exception) -> None:
    detail = f'missing field {exc}' if isinstance(exc, KeyError) else str(exc)
    print(f'ERROR: {detail}', file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description='Detect D-LogM clips and preview the LUT')
    parser.add_argument('project')
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('detect', help='list clips as unknown with their camera source')
    sub.add_parser('show', help='print the recorded per-file LUT decisions')
    pv = sub.add_parser('preview')
    pv.add_argument('file')
    pv.add_argument('t', type=float)
    st = sub.add_parser('set', help='record LUT decisions in moments.json and clips.json')
    st.add_argument('decisions', nargs='*', metavar='FILE=true|false')
    st.add_argument('--all', dest='all_value', choices=['true', 'false'])
    args = parser.parse_args()
    root = Path(args.project).expanduser()
    if args.cmd == 'set':
        try:
            files = [c['file'] for c in read_json(root / 'probe.json')['clips']]
            all_value = None if args.all_value is None else _bool(args.all_value)
            decisions = parse_decisions(args.decisions, all_value, files)
            changed = set_decisions(root, decisions)
        except (OSError, ValueError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            sys.exit(1)
        on = sum(decisions.values())
        print(f'moments.json lut: {on} on, {len(decisions) - on} off')
        print('\n'.join(changed) if changed else 'clips.json: no flag changes')
        return
    if args.cmd == 'detect':
        try:
            found = detect(root)
        except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
            _fail(exc)
        for file, (status, source) in sorted(found.items()):
            print(f'{status}  {source:<5}  {file}')
        return
    if args.cmd == 'show':
        try:
            lines, mismatches = show(root)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            _fail(exc)
        print('\n'.join(lines))
        if mismatches:
            print('\n'.join(mismatches))
            sys.exit(1)
        if (root / 'clips.json').exists():
            print(f'clips.json: {len(read_json(root / "clips.json"))} clips match')
        else:
            print('clips.json: not written yet')
        return
    src = root / args.file
    out = cache_dir(root) / f'lut-preview-{src.stem}-{args.t:.1f}.jpg'
    print(preview(src, args.t, out))


if __name__ == '__main__':
    main()
