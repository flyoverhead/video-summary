#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import cache_dir, defaults, read_json, run  # noqa: E402

INSTALL = '''brew install whisper-cpp
mkdir -p ~/.cache/whisper.cpp && curl -L -o ~/.cache/whisper.cpp/ggml-large-v3-turbo.bin \\
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin'''


def whisper_paths() -> tuple[str, Path]:
    cfg = defaults()['speech']
    name = os.environ.get('VIDEO_SUMMARY_WHISPER_BIN') or cfg['bin']
    if '/' in name:
        binary = name
    else:
        search = os.environ.get('PATH', '') + ':' + cfg['extra_path']
        binary = shutil.which(name, path=search) or name
    model = os.environ.get('VIDEO_SUMMARY_WHISPER_MODEL') or cfg['model']
    return binary, Path(model).expanduser()


def _runnable(binary: str) -> bool:
    try:
        res = subprocess.run([binary, '--help'], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return res.returncode == 0


def check() -> list[str]:
    binary, model = whisper_paths()
    problems = []
    if '/' not in binary or not os.access(binary, os.X_OK):
        problems.append(f'whisper-cli not found: {binary}')
    elif not _runnable(binary):
        problems.append(f'whisper-cli not runnable: {binary}')
    if not model.is_file():
        problems.append(f'model not found: {model}')
    return problems


HALLUCINATIONS = {
    'thank you',
    'thanks for watching',
    'you',
    'продолжение следует',
    'субтитры сделал dimatorzok',
    'субтитры создавал dimatorzok',
    'редактор субтитров а синецкая корректор а егорова',
    'спасибо за просмотр',
}


def _normalize(text: str) -> str:
    return ' '.join(re.sub(r'[^\w\s]', ' ', text.casefold()).split())


def transcript_path(root: Path, file: str) -> Path:
    return cache_dir(root) / 'speech' / (hashlib.sha1(file.encode()).hexdigest()[:16] + '.json')


def load_transcript(root: Path, file: str) -> dict | None:
    path = transcript_path(root, file)
    return read_json(path) if path.exists() else None


def _eligible(root: Path) -> list[str]:
    import sample

    clips = sample._load_probe(root)['clips']
    excluded = set(sample.force_excluded(root, clips))
    return [c['file'] for c in clips if c['audio_channels'] > 0 and c['file'] not in excluded]


def needs_transcript(root: Path) -> list[str]:
    return [f for f in _eligible(root) if not transcript_path(root, f).exists()]


def parse_whisper_json(data: dict) -> tuple[str | None, list[dict]]:
    language = (data.get('result') or {}).get('language')
    segments = [{'start': round(e['offsets']['from'] / 1000, 3),
                 'end': round(e['offsets']['to'] / 1000, 3),
                 'text': e['text'].strip()} for e in data.get('transcription') or []]
    return language, segments


def filter_segments(segments: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for seg in segments:
        norm = _normalize(seg['text'])
        if not norm or norm in HALLUCINATIONS:
            continue
        if kept and kept[-1]['text'] == seg['text']:
            continue
        kept.append(seg)
    return kept


def silences(path: Path) -> list[list[float]]:
    cfg = defaults()['speech']
    af = f'pan=mono|c0=c0,silencedetect=noise={cfg["silence_db"]}dB:d={cfg["silence_min_s"]}'
    res = run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path), '-vn', '-af', af, '-f', 'null', '-'])
    log = res.stderr
    dur = re.search(r'Duration: (\d+):(\d+):([\d.]+)', log)
    duration = int(dur[1]) * 3600 + int(dur[2]) * 60 + float(dur[3]) if dur else 0.0
    found: list[list[float]] = []
    start = None
    for line in log.splitlines():
        if m := re.search(r'silence_start: (-?[\d.]+)', line):
            start = max(0.0, float(m[1]))
        elif (m := re.search(r'silence_end: (-?[\d.]+)', line)) and start is not None:
            found.append([round(start, 3), round(float(m[1]), 3)])
            start = None
    if start is not None and duration > start:
        found.append([round(start, 3), round(duration, 3)])
    return found


def _write_transcript(root: Path, file: str, language, segments, sil, error) -> None:
    path = transcript_path(root, file)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {'file': file, 'language': language, 'segments': segments, 'silences': sil, 'error': error}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n')


def _transcribe_clip(root: Path, file: str, tmp: Path, binary: str, model: Path) -> dict:
    stem = hashlib.sha1(file.encode()).hexdigest()[:16]
    wav, base = tmp / f'{stem}.wav', tmp / stem
    out = base.with_suffix('.json')
    try:
        src = Path(root) / file
        run(['ffmpeg', '-v', 'error', '-y', '-i', str(src), '-vn', '-af', 'pan=mono|c0=c0',
             '-ar', '16000', '-c:a', 'pcm_s16le', str(wav)])
        res = run([binary, '-m', str(model), '-f', str(wav), '-l', 'auto', '-oj', '-of', str(base), '-np'],
                  check=False)
        if res.returncode != 0:
            raise RuntimeError(f'whisper exit {res.returncode}: {(res.stderr or "").strip()[-200:]}')
        try:
            language, segments = parse_whisper_json(json.loads(out.read_text()))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RuntimeError(f'unparsable whisper output: {exc}') from exc
        segments = filter_segments(segments)
        sil = silences(src)
        _write_transcript(root, file, language, segments, sil, None)
        return {'language': language, 'segments': segments}
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        detail = (getattr(exc, 'stderr', None) or str(exc)).strip()[-300:]
        _write_transcript(root, file, None, [], [], detail or 'transcription failed')
        return {'error': detail or 'transcription failed'}
    finally:
        wav.unlink(missing_ok=True)
        out.unlink(missing_ok=True)


def transcribe_project(root: Path, overwrite: bool = False, progress=print) -> dict:
    files = _eligible(root) if overwrite else needs_transcript(root)
    binary, model = whisper_paths()
    tmp = cache_dir(root) / 'speech' / 'tmp'
    tmp.mkdir(parents=True, exist_ok=True)
    summary = {'clips': len(files), 'with_speech': 0, 'segments': 0, 'languages': [], 'failed': []}
    for file in files:
        result = _transcribe_clip(root, file, tmp, binary, model)
        if 'error' in result:
            summary['failed'].append(file)
            progress(f'{file}: failed')
            continue
        if result['segments']:
            summary['with_speech'] += 1
            summary['segments'] += len(result['segments'])
        lang = result['language']
        if lang and lang not in summary['languages']:
            summary['languages'].append(lang)
        progress(f'{file}: {len(result["segments"])} segments')
    return summary


def said_at(segments: list[dict], t: float, before: float, after: float, limit: int) -> str | None:
    lo, hi = t - before, t + after
    text = ' '.join(s['text'] for s in segments if s['end'] >= lo and s['start'] <= hi)
    if not text:
        return None
    return text if len(text) <= limit else text[:limit - 1] + '…'


def cmd_check(_args) -> int:
    problems = check()
    if problems:
        for problem in problems:
            print(problem)
        print(INSTALL)
        return 1
    binary, model = whisper_paths()
    print(f'whisper-cli: {binary}')
    print(f'model: {model}')
    return 0


def cmd_transcribe(args) -> int:
    problems = check()
    if problems:
        for problem in problems:
            print(problem)
        print(INSTALL)
        return 1
    summary = transcribe_project(Path(args.project), overwrite=args.overwrite)
    line = f'{summary["clips"]} clips, {summary["with_speech"]} with speech, {summary["segments"]} segments'
    if summary['languages']:
        line += ', language ' + ', '.join(summary['languages'])
    print(line)
    for file in summary['failed']:
        error = (load_transcript(Path(args.project), file) or {}).get('error')
        print(f'failed: {file}: {error}')
    return 0


def _unsampled(root: Path, files: list[str], candidates: list[dict]) -> list[str]:
    import sample

    cfg, scfg = defaults()['sampling'], defaults()['speech']
    durations = {c['file']: c['duration'] for c in read_json(root / 'probe.json')['clips']}
    found = []
    for file in files:
        transcript = load_transcript(root, file)
        if not transcript:
            continue
        top = max(0.0, durations[file] - sample.END_MARGIN)
        have = [c['t'] for c in candidates if c.get('file') == file]
        times = sample.speech_times(transcript['segments'], durations[file], cfg['min_gap_s'], scfg['max_per_min'])
        if any(all(abs(min(t, top) - h) >= cfg['min_gap_s'] for h in have) for t in times):
            found.append(file)
    return found


def _first(label: str, files: list[str]) -> None:
    if files:
        print(f'{label}: {len(files)} (first: {files[0]})')


def cmd_status(args) -> int:
    root = Path(args.project)
    if not (root / 'probe.json').exists():
        print('no probe.json')
        print('speech: not analysed')
        return 1
    try:
        eligible = _eligible(root)
    except (OSError, ValueError, KeyError) as exc:
        print(f'cannot read probe.json: {exc}')
        print('speech: not analysed')
        return 1
    missing = [f for f in eligible if not transcript_path(root, f).exists()]
    print(f'transcripts missing: {len(missing)}')
    for file in missing[:5]:
        print(f'  {file}')
    if len(missing) > 5:
        print(f'  ... and {len(missing) - 5} more')
    present = [f for f in eligible if f not in missing]
    transcripts, unreadable = {}, []
    for file in present:
        try:
            transcripts[file] = load_transcript(root, file) or {}
        except ValueError:
            unreadable.append(file)
    _first('transcript unreadable', unreadable)
    _first('transcription failed', [f for f, t in transcripts.items() if t.get('error')])
    moments_path = root / 'moments.json'
    unsampled = []
    if moments_path.exists():
        candidates = read_json(moments_path).get('candidates', [])
        print(f'speech candidates: {sum(1 for c in candidates if c.get("source") == "speech")}')
        unsampled = _unsampled(root, list(transcripts), candidates)
        _first('speech not sampled', unsampled)
    else:
        print('speech candidates: no moments.json')
    ok = not missing and not unsampled and not unreadable
    print('speech: ok' if ok else 'speech: not analysed')
    return 0 if ok else 1


def cmd_show(args) -> int:
    transcript = load_transcript(Path(args.project), args.file)
    if transcript is None:
        print(f'no transcript for {args.file}', file=sys.stderr)
        return 1
    for seg in transcript['segments']:
        if args.start is not None and seg['end'] < args.start:
            continue
        if args.end is not None and seg['start'] > args.end:
            continue
        print(f'{seg["start"]:g}–{seg["end"]:g} {seg["text"]}')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('check', help='verify whisper-cli and the model are installed').set_defaults(func=cmd_check)
    tr = sub.add_parser('transcribe', help='transcribe clips into the cache')
    tr.add_argument('project')
    tr.add_argument('--overwrite', action='store_true')
    tr.set_defaults(func=cmd_transcribe)
    st = sub.add_parser('status', help='report whether speech was analysed for a project')
    st.add_argument('project')
    st.set_defaults(func=cmd_status)
    sh = sub.add_parser('show', help='print a clip transcript')
    sh.add_argument('project')
    sh.add_argument('file')
    sh.add_argument('--from', dest='start', type=float)
    sh.add_argument('--to', dest='end', type=float)
    sh.set_defaults(func=cmd_show)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
