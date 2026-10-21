#!/usr/bin/env python3
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DRAFT_NAME, LUT_PATH, defaults, output_path, read_json, run  # noqa: E402
from filters import audio_filter, fps_expr, music_args, scale_frame, video_filter  # noqa: E402
from verify import validate  # noqa: E402

FONTS = ('/System/Library/Fonts/SFNS.ttf', '/System/Library/Fonts/Helvetica.ttc',
         '/System/Library/Fonts/Supplemental/Arial.ttf')


def find_font() -> Path:
    for font in FONTS:
        if Path(font).exists():
            return Path(font)
    raise FileNotFoundError(f'no usable font, tried: {", ".join(FONTS)}')


def _ffmpeg(cmd: list[str], what: str) -> None:
    try:
        run(cmd)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f'{what} failed:\n{(exc.stderr or "")[-800:]}') from exc


def concat_entry(path: Path) -> str:
    return "file '" + str(path).replace("'", "'\\''") + "'\n"


def _validate(config: dict, clips: list[dict], probe: dict) -> None:
    if not isinstance(config, dict) or 'src' not in config:
        raise ValueError('config.json must be an object with "src"')
    problems = validate(Path(config['src']), config, clips, probe)
    if problems:
        raise ValueError('refusing to render:\n' + '\n'.join(f'  {p}' for p in problems))


def _clip_cmd(clip: dict, src: dict, source: Path, dest: Path, vf: str, quality: int, audio_br: str,
              fps: str) -> list[str]:
    start, dur = f'{clip["start"]:.3f}', f'{clip["duration"]:.3f}'
    cmd = ['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-ss', start, '-i', str(source)]
    af = audio_filter(src)
    if af is None:
        cmd += ['-f', 'lavfi', '-t', dur, '-i', 'anullsrc=r=48000:cl=mono']
    cmd += ['-t', dur, '-map', '0:v:0', '-map', '0:a:0' if af else '1:a:0', '-vf', vf]
    if af:
        cmd += ['-af', af]
    return cmd + ['-c:v', 'hevc_videotoolbox', '-q:v', str(quality), '-tag:v', 'hvc1',
                  '-c:a', 'aac', '-b:a', audio_br, '-ar', '48000', '-ac', '1', '-r', fps, str(dest)]


def _path(value) -> Path:
    return Path(str(value)).expanduser().resolve()


def render(config: dict, clips: list[dict], probe: dict, draft: bool = False,
           overwrite: bool = False) -> Path:
    _validate(config, clips, probe)
    sources = {c['file']: c for c in probe['clips']}
    rcfg = defaults()['render']
    out = _path(config['out'])
    frame = dict(config['frame'])
    audio_br = config.get('audio_br', rcfg['audio_br'])
    if draft:
        frame = scale_frame(frame, config.get('draft_long_side', rcfg['draft_long_side']))
        quality, pix_fmt = config.get('draft_quality', rcfg['draft_quality']), 'yuv420p'
        target = output_path(out.parent, DRAFT_NAME)
    else:
        quality, pix_fmt = config['quality'], 'yuv420p10le'
        target = output_path(out.parent, out.name)
        if target.exists() and not overwrite:
            raise FileExistsError(str(target))
    tmp_root = _path(config['tmp'])
    work = tmp_root / ('draft' if draft else 'final')
    work.mkdir(parents=True, exist_ok=True)
    lut = _path(config['lut']) if config.get('lut') else LUT_PATH
    font = find_font()
    fps = fps_expr(frame['fps'])
    src_root = _path(config['src'])

    processed, manifest = [], []
    for i, clip in enumerate(clips):
        src = sources[clip['file']]
        start, dur = float(clip['start']), float(clip['duration'])
        print(f'[{i + 1}/{len(clips)}] {clip["file"]} [{start:.1f}→{start + dur:.1f}] "{clip["label"]}"',
              flush=True)
        dest = work / f'clip_{i:03d}.mp4'
        vf = video_filter(clip, src, frame, lut, font, pix_fmt)
        _ffmpeg(_clip_cmd(clip, src, src_root / clip['file'], dest, vf, quality, audio_br, fps),
                f'clip {i + 1} ({clip["file"]})')
        processed.append(dest)
        manifest.append({'index': i, 'file': clip['file'], 'lut': bool(clip['lut']), 'duration': dur})

    concat = work / 'concat.txt'
    concat.write_text(''.join(concat_entry(p.resolve()) for p in processed))
    video_s = sum(c['duration'] for c in manifest)
    music = config.get('music')
    merged = work / 'summary.mp4'
    cmd = ['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat)]
    if music:
        cmd += music_args({'duck_db': rcfg['duck_db'], **music, 'file': str(_path(music['file']))}, video_s)
    cmd += ['-c:v', 'copy', '-c:a', 'aac', '-ac', '2', '-b:a', audio_br, '-movflags', '+faststart', str(merged)]
    print(f'Concatenating {len(processed)} clips...', flush=True)
    _ffmpeg(cmd, 'concat')
    shutil.move(str(merged), str(target))

    (tmp_root / 'render-manifest.json').write_text(
        json.dumps({'clips': manifest, 'draft': draft, 'out': str(target)}, indent=2, ensure_ascii=False) + '\n')
    print(f'Done!  {target}', flush=True)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description='Render the summary video from clips.json')
    parser.add_argument('project')
    parser.add_argument('--draft', action='store_true', help=f'fast low-res preview to {DRAFT_NAME}')
    parser.add_argument('--overwrite', action='store_true', help='replace an existing final output')
    args = parser.parse_args()
    project = Path(args.project).expanduser()
    try:
        config, clips, probe = (read_json(project / n) for n in ('config.json', 'clips.json', 'probe.json'))
        if isinstance(config, dict) and 'src' in config and _path(config['src']) != project.resolve():
            raise ValueError(f'config.src {config["src"]} is not the project folder {project.resolve()}')
        render(config, clips, probe, draft=args.draft, overwrite=args.overwrite)
    except FileExistsError as exc:
        raise SystemExit(f'exists, use --overwrite: {exc}')
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f'ERROR: {exc}')


if __name__ == '__main__':
    main()
