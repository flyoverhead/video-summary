#!/usr/bin/env python3
import argparse
import difflib
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
from common import LUT_PATH, cache_dir, cache_slug, defaults, output_path, read_json, run, write_output  # noqa: E402
from filters import escape_drawtext  # noqa: E402
from lut import escape_filter_path  # noqa: E402
from probe import _shape  # noqa: E402
from render_summary import find_font  # noqa: E402
from sample import _run_hw  # noqa: E402

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


def _tile_filter(lut: Path | None, width: int, height: int, text: str, font: Path) -> str:
    chain = [f'lut3d=file={escape_filter_path(lut)}'] if lut else []
    size = max(10, round(height / 14))
    chain += [f'scale={width}:{height}:force_original_aspect_ratio=decrease',
              f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black', 'setsar=1',
              f'drawtext=fontfile={escape_filter_path(font)}'
              f':text={escape_filter_path(escape_drawtext(text))}'
              f':x=4:y=4:fontsize={size}:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=3']
    return ','.join(chain)


def _sheet_frame(src: Path, t: float, out: Path, vf: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run_hw(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-ss', f'{t:.3f}', '-i', str(src),
                 '-frames:v', '1', '-vf', vf, '-q:v', '3', str(out)])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f'contact sheet frame failed at {t:.3f}s in {src}: {(exc.stderr or "").strip()[-400:]}') from exc
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f'no frame at {t:.3f}s in {src}')


def contact_sheet(project: Path, clips: list[dict]) -> list[Path]:
    project = Path(project)
    cfg = defaults()['sheet']
    cols, rows, tile_w = int(cfg['cols']), int(cfg['rows']), int(cfg['tile_width'])
    frame = read_json(project / 'probe.json')['frame']
    tile_h = max(2, round(tile_w * frame['height'] / frame['width'] / 2) * 2)
    config_path = project / 'config.json'
    lut = Path(read_json(config_path).get('lut') or LUT_PATH) if config_path.exists() else LUT_PATH
    font = find_font()
    root = cache_dir(project) / 'sheet'
    for stale in root.glob('contact-sheet-*.png'):
        stale.unlink()
    frames = []
    for n, clip in enumerate(clips, 1):
        src = project / clip['file']
        if not src.is_file():
            raise FileNotFoundError(f'clip #{n}: source not found: {src}')
        t = float(clip['start']) + float(clip['duration']) / 2
        use_lut = bool(clip.get('lut'))
        text = f'#{n} {clip.get("label", "")}'.rstrip()
        key = f'{clip["file"]}|{t:.3f}|{use_lut}|{tile_w}x{tile_h}|{text}'
        out = root / 'frames' / f'{hashlib.sha1(key.encode()).hexdigest()[:16]}.jpg'
        if not out.exists() or out.stat().st_size == 0:
            _sheet_frame(src, t, out, _tile_filter(lut if use_lut else None, tile_w, tile_h, text, font))
        frames.append(out)
    per_page = cols * rows
    pages = []
    for page_no, first in enumerate(range(0, len(frames), per_page), 1):
        chunk = frames[first:first + per_page]
        seq = root / 'seq'
        shutil.rmtree(seq, ignore_errors=True)
        seq.mkdir(parents=True)
        for i, frame_path in enumerate(chunk, 1):
            (seq / f'{i:04d}.jpg').symlink_to(frame_path)
        page = root / f'contact-sheet-{page_no:02d}.png'
        try:
            run(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-framerate', '1', '-i', str(seq / '%04d.jpg'),
                 '-vf', f'tile={cols}x{rows}:color=black', '-frames:v', '1', str(page)])
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f'contact sheet page {page_no} failed: {(exc.stderr or "").strip()[-400:]}') from exc
        finally:
            shutil.rmtree(seq, ignore_errors=True)
        pages.append(page)
    return pages


def clean_cache(project: Path) -> tuple[Path, int]:
    root = common.CACHE_ROOT.resolve()
    link = common.CACHE_ROOT / cache_slug(project)
    if link.is_symlink():
        raise ValueError(f'refusing to clean {link}: symlink')
    path = link.resolve()
    if path.parent != root:
        raise ValueError(f'refusing to clean {path}: not a direct child of {root}')
    if not path.is_dir():
        return path, 0
    render = path / 'render'
    keep = set() if render.is_symlink() else {f for f in path.glob('render/render-manifest.*.json') if not f.is_symlink()}
    freed = sum(f.stat().st_size for f in path.rglob('*') if f.is_file() and not f.is_symlink() and f not in keep)
    if not keep:
        shutil.rmtree(path)
        return path, freed
    for entry in path.iterdir():
        if entry != render:
            shutil.rmtree(entry) if entry.is_dir() and not entry.is_symlink() else entry.unlink()
    for entry in render.iterdir():
        if entry not in keep:
            shutil.rmtree(entry) if entry.is_dir() and not entry.is_symlink() else entry.unlink()
    return path, freed


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
    sh = sub.add_parser('sheet', help='render contact-sheet pages of the clips; print page paths')
    sh.add_argument('project')
    sh.add_argument('clips', help='clips.json array file, or - for stdin')
    cl = sub.add_parser('clean', help="remove the project's cache folder")
    cl.add_argument('project')
    args = parser.parse_args()
    root = Path(args.project).expanduser()
    if not root.is_dir():
        print(f'ERROR: project folder not found: {root}', file=sys.stderr)
        sys.exit(2)
    try:
        if args.cmd == 'summary':
            print(summary(root), end='')
            return
        if args.cmd == 'clean':
            if not (common.CACHE_ROOT / cache_slug(root)).exists():
                print(f'no cache for {root}')
                return
            path, freed = clean_cache(root)
            kept = ', kept render manifest' if any(f.is_file() and not f.is_symlink() for f in path.glob('render/render-manifest.*.json')) else ''
            print(f'removed {path} ({freed / 1e6:.1f} MB){kept}')
            return
        if args.cmd == 'sheet':
            raw = sys.stdin.read() if args.clips == '-' else Path(args.clips).expanduser().read_text()
            for page in contact_sheet(root, json.loads(raw)):
                print(page)
            return
        raw = sys.stdin.read() if args.src == '-' else Path(args.src).expanduser().read_text()
        status, diff = write(root, args.name, raw, overwrite=args.overwrite)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
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
