#!/usr/bin/env python3
import argparse
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import cache_dir, defaults, output_path, read_json, run, write_output  # noqa: E402
from probe import _ffprobe, collect_probe  # noqa: E402

PRIORITY = {'scene': 0, 'loud': 1, 'baseline': 2}
END_MARGIN = 0.05
LOUD_WINDOW_S = 0.2
LOUD_MIN_SEPARATION_S = 1.0


def _run_hw(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return run(cmd[:1] + ['-hwaccel', 'videotoolbox'] + cmd[1:])
    except subprocess.CalledProcessError:
        return run(cmd)


def scene_times(path: Path, threshold: float) -> list[float]:
    cmd = ['ffmpeg', '-hide_banner', '-nostats', '-v', 'info', '-i', str(path), '-an',
           '-vf', f'scale=320:-2,scdet=threshold={threshold}', '-f', 'null', '-']
    proc = _run_hw(cmd)
    found = re.findall(r'lavfi\.scd\.time:\s*([0-9.]+)', proc.stderr)
    return sorted({round(float(t), 3) for t in found})


def _has_audio(path: Path) -> bool:
    return bool(_ffprobe(path, 'a:0').get('streams'))


def loud_times(path: Path, top_k: int, over_median: float) -> list[float]:
    if not _has_audio(path):
        return []
    proc = run(['ffmpeg', '-hide_banner', '-nostats', '-v', 'error', '-i', str(path), '-vn',
                '-af', 'ebur128=metadata=1,ametadata=mode=print:key=lavfi.r128.M:file=-',
                '-f', 'null', '-'])
    series: list[tuple[float, float]] = []
    when = None
    for line in proc.stdout.splitlines():
        if 'pts_time:' in line:
            when = float(line.rsplit('pts_time:', 1)[1])
        elif line.startswith('lavfi.r128.M=') and when is not None:
            value = float(line.split('=', 1)[1])
            if value > -70:
                series.append((when, value))
    if len(series) < 3:
        return []
    median = statistics.median(v for _, v in series)
    peaks = []
    for i in range(1, len(series) - 1):
        t, v = series[i]
        if v >= series[i - 1][1] and v > series[i + 1][1] and v - median > over_median:
            peaks.append((v, t))
    chosen: list[float] = []
    for _, t in sorted(peaks, reverse=True):
        if all(abs(t - c) >= LOUD_MIN_SEPARATION_S for c in chosen):
            chosen.append(t)
        if len(chosen) == top_k:
            break
    return sorted(round(max(0.0, t - LOUD_WINDOW_S), 3) for t in chosen)


def baseline_times(duration: float, every: float) -> list[float]:
    if duration < every:
        return [round(duration / 2, 3)]
    times = []
    t = every / 2
    while t < duration:
        times.append(round(t, 3))
        t += every
    return times


def merge_times(tagged: list[tuple[float, str]], duration: float, min_gap: float) -> list[tuple[float, str]]:
    top = max(0.0, duration - END_MARGIN)
    clamped = [(round(min(max(t, 0.0), top), 3), src) for t, src in tagged]
    kept: list[tuple[float, str]] = []
    for t, src in sorted(clamped, key=lambda x: (PRIORITY[x[1]], x[0])):
        if all(abs(t - k) >= min_gap for k, _ in kept):
            kept.append((t, src))
    return sorted(kept)


def extract_thumb(path: Path, t: float, out: Path, width: int) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    try:
        _run_hw(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-ss', f'{t:.3f}', '-i', str(path),
                  '-frames:v', '1', '-vf', f'scale={width}:-2', '-q:v', '4', str(out)])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f'thumbnail failed at {t:.3f}s in {path}: {(exc.stderr or "").strip()}') from exc
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f'no frame at {t:.3f}s in {path}')
    return out


def _load_probe(root: Path) -> dict:
    probe = Path(root) / 'probe.json'
    return read_json(probe) if probe.exists() else collect_probe(root)


def force_excluded(root: Path, clips: list[dict]) -> list[str]:
    brief = Path(root) / 'brief.json'
    entries = set(read_json(brief).get('force_exclude') or []) if brief.exists() else set()
    return [c['file'] for c in clips
            if c['file'] in entries or Path(c['file']).name in entries
            or any(parent.as_posix() in entries for parent in Path(c['file']).parents)]


def _clip_times(path: Path, duration: float, cfg: dict) -> list[tuple[float, str]]:
    tagged = [(t, 'scene') for t in scene_times(path, cfg['scene_threshold'])]
    tagged += [(t, 'loud') for t in loud_times(path, cfg['loud_top_k'], cfg['loud_min_lufs_over_median'])]
    tagged += [(t, 'baseline') for t in baseline_times(duration, cfg['baseline_every_s'])]
    return merge_times(tagged, duration, cfg['min_gap_s'])


def _candidate(root: Path, cid: str, clip: dict, t: float, source: str, width: int,
               skipped: list[str] | None) -> dict | None:
    thumb = cache_dir(root) / 'thumbs' / f'{cid}.jpg'
    try:
        extract_thumb(Path(root) / clip['file'], t, thumb, width)
    except RuntimeError as exc:
        note = f'{clip["file"]} @ {t:g}s: {exc}'
        print(f'warning: skipped {note}', file=sys.stderr)
        if skipped is not None:
            skipped.append(note)
        return None
    return {'id': cid, 'file': clip['file'], 't': t, 'source': source, 'thumb': str(thumb)}


def sample_project(root: Path, overwrite: bool = False, skipped: list[str] | None = None) -> dict:
    root = Path(root)
    if output_path(root, 'moments.json').exists() and not overwrite:
        raise FileExistsError(str(root / 'moments.json'))
    cfg = defaults()['sampling']
    if overwrite:
        shutil.rmtree(cache_dir(root) / 'scores', ignore_errors=True)
    candidates = []
    clips = _load_probe(root)['clips']
    excluded = set(force_excluded(root, clips))
    for clip in clips:
        if clip['file'] in excluded:
            continue
        path = root / clip['file']
        for t, source in _clip_times(path, clip['duration'], cfg):
            cand = _candidate(root, f'c{len(candidates) + 1:04d}', clip, t, source, cfg['thumb_width'], skipped)
            if cand:
                candidates.append(cand)
    data = {'candidates': candidates, 'scores': {}, 'groups': [], 'must_find': []}
    write_output(root, 'moments.json', data, overwrite=overwrite)
    return data


def rescan(root: Path, files: list[str], every: float, skipped: list[str] | None = None) -> list[dict]:
    root = Path(root)
    cfg = defaults()['sampling']
    data = read_json(root / 'moments.json')
    clips = {c['file']: c for c in _load_probe(root)['clips']}
    unknown = [f for f in files if f not in clips]
    if unknown:
        raise ValueError(f'not in probe: {", ".join(unknown)}')
    last = max((int(c['id'][1:]) for c in data['candidates']), default=0)
    new = []
    for file in files:
        clip = clips[file]
        have = [c['t'] for c in data['candidates'] if c['file'] == file]
        for t in baseline_times(clip['duration'], every):
            t = round(min(t, max(0.0, clip['duration'] - END_MARGIN)), 3)
            if any(abs(t - h) < every / 4 for h in have):
                continue
            cand = _candidate(root, f'c{last + 1:04d}', clip, t, 'baseline', cfg['thumb_width'], skipped)
            if cand:
                last += 1
                new.append(cand)
                have.append(t)
    data['candidates'] += new
    write_output(root, 'moments.json', data, overwrite=True)
    return new


def main() -> None:
    parser = argparse.ArgumentParser(description='Pick candidate moments and extract thumbnails')
    parser.add_argument('project')
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--rescan', nargs='+', metavar='FILE')
    parser.add_argument('--every', type=float, default=2.0)
    args = parser.parse_args()
    root = Path(args.project).expanduser()
    skipped: list[str] = []
    if args.rescan:
        new = rescan(root, args.rescan, args.every, skipped)
        print(f'added {len(new)} candidates')
    else:
        try:
            data = sample_project(root, overwrite=args.overwrite, skipped=skipped)
        except FileExistsError as exc:
            raise SystemExit(f'exists, use --overwrite: {exc}')
        counts = {s: sum(1 for c in data['candidates'] if c['source'] == s) for s in PRIORITY}
        print(f'{len(data["candidates"])} candidates: {counts}')
        excluded = force_excluded(root, _load_probe(root)['clips'])
        if excluded:
            print(f'not sampled (force_exclude): {", ".join(excluded)}')
    if skipped:
        print(f'skipped {len(skipped)} timestamp{"s" if len(skipped) > 1 else ""} (no thumbnail):')
        print('\n'.join(f'  {note}' for note in skipped))


if __name__ == '__main__':
    main()
