import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
LUT_PATH = PLUGIN_ROOT / 'assets' / 'luts' / 'dji-osmo-action6-dlogm-to-rec709.cube'
FFMPEG_BIN = '/opt/homebrew/opt/ffmpeg-full/bin'
CAMERA_ROOT = Path.home() / 'Movies' / 'camera'
CACHE_ROOT = Path.home() / '.cache' / 'video-summary'

ALLOWED_OUTPUTS = frozenset({
    'brief.json',
    'probe.json',
    'moments.json',
    'clips.json',
    'config.json',
    'SUMMARY.md',
})
FINAL_NAME = 'SUMMARY_VIDEO.mp4'
DRAFT_NAME = 'SUMMARY_VIDEO.draft.mp4'
VIDEO_OUTPUTS = frozenset({FINAL_NAME, DRAFT_NAME})


def ffmpeg_env() -> dict[str, str]:
    env = dict(os.environ)
    env['PATH'] = FFMPEG_BIN + ':' + env.get('PATH', '')
    return env


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    kw.setdefault('text', True)
    kw.setdefault('capture_output', True)
    kw.setdefault('env', ffmpeg_env())
    kw.setdefault('check', True)
    return subprocess.run(cmd, **kw)


def output_path(project: Path, name: str) -> Path:
    if name in ALLOWED_OUTPUTS or name in VIDEO_OUTPUTS:
        return Path(project) / name
    raise ValueError(f'output name not allowed: {name}')


def write_output(project: Path, name: str, data: dict | list | str, overwrite: bool = False) -> Path:
    path = output_path(project, name)
    if path.exists() and not overwrite:
        raise FileExistsError(str(path))
    if isinstance(data, str):
        path.write_text(data)
    else:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    return path


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text())


def cache_dir(project: Path) -> Path:
    project = Path(project).resolve()
    try:
        slug = str(project.relative_to(CAMERA_ROOT.resolve())).replace('/', '-')
    except ValueError:
        slug = f'{project.name}-{hashlib.sha1(str(project).encode()).hexdigest()[:8]}'
    path = CACHE_ROOT / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def defaults() -> dict:
    return read_json(Path(__file__).resolve().parent / 'defaults.json')
