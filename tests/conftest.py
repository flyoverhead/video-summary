import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'video-summary' / 'scripts'))

import common  # noqa: E402
from common import run  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path_factory, monkeypatch):
    monkeypatch.setattr(common, 'CACHE_ROOT', tmp_path_factory.mktemp('cache'))


def _encoders():
    out = run(['ffmpeg', '-hide_banner', '-encoders']).stdout
    return 'libx265' in out


def _hevc_args():
    if _encoders():
        return ['-c:v', 'libx265', '-pix_fmt', 'yuv420p10le', '-x265-params', 'log-level=error',
                '-tag:v', 'hvc1']
    return ['-c:v', 'hevc_videotoolbox', '-profile:v', 'main10', '-pix_fmt', 'p010le', '-tag:v', 'hvc1']


def _build(path, video, duration, fps, audio=None):
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', video]
    if audio:
        cmd += ['-f', 'lavfi', '-i', audio]
    cmd += ['-t', str(duration), '-r', str(fps)] + _hevc_args()
    if audio:
        cmd += ['-c:a', 'aac', '-b:a', '128k']
    else:
        cmd += ['-an']
    cmd.append(str(path))
    run(cmd)
    return path


@pytest.fixture(scope='session')
def clips_dir(tmp_path_factory):
    return tmp_path_factory.mktemp('clips')


@pytest.fixture(scope='session')
def square_clip(clips_dir):
    return _build(clips_dir / 'square.MP4', 'testsrc2=s=320x320:r=25:d=3', 3, 25,
                  'sine=frequency=440:sample_rate=48000:d=3')


@pytest.fixture(scope='session')
def wide_clip(clips_dir):
    return _build(clips_dir / 'wide.MP4', 'testsrc2=s=480x270:r=50:d=3', 3, 50,
                  'sine=frequency=330:sample_rate=48000:d=3,aformat=channel_layouts=stereo')


@pytest.fixture(scope='session')
def vertical_clip(clips_dir):
    return _build(clips_dir / 'vertical.MP4', 'testsrc2=s=270x480:r=30000/1001:d=3', 3, '30000/1001',
                  'sine=frequency=550:sample_rate=48000:d=3')


@pytest.fixture(scope='session')
def cut_clip(clips_dir):
    video = ('color=c=red:s=320x320:r=25:d=1.5[a];color=c=blue:s=320x320:r=25:d=1.5[b];'
             '[a][b]concat=n=2:v=1:a=0')
    return _build(clips_dir / 'cut.MP4', video, 3, 25, 'sine=frequency=440:sample_rate=48000:d=3')


@pytest.fixture(scope='session')
def loud_clip(clips_dir):
    audio = "aevalsrc='sin(2*PI*440*t)*if(between(t,2.0,2.3),1,0.01)':s=48000:d=4"
    return _build(clips_dir / 'loud.MP4', 'testsrc2=s=320x320:r=25:d=4', 4, 25, audio)


@pytest.fixture(scope='session')
def short_clip(clips_dir):
    return _build(clips_dir / 'short.MP4', 'testsrc2=s=320x320:r=25:d=0.8', 0.8, 25,
                  'sine=frequency=440:sample_rate=48000:d=0.8')


@pytest.fixture(scope='session')
def silent_clip(clips_dir):
    return _build(clips_dir / 'silent.MP4', 'testsrc2=s=320x320:r=25:d=2', 2, 25)


@pytest.fixture
def project(tmp_path, square_clip, wide_clip, vertical_clip):
    root = tmp_path / 'trip dir'
    for day in ('22.08', '25.08'):
        (root / day).mkdir(parents=True)
    shutil.copy(square_clip, root / '22.08' / 'square.MP4')
    shutil.copy(wide_clip, root / '22.08' / 'wide.MP4')
    shutil.copy(vertical_clip, root / '25.08' / 'vertical.MP4')
    (root / '22.08' / 'square.LRF').write_bytes(b'dummy')
    return root


def build_render_project(root, sources, tmp, frame=None, music=None, **extra):
    import probe

    root.mkdir(parents=True, exist_ok=True)
    clips = []
    for src, name, label, lut in sources:
        dest = root / name
        if not dest.exists():
            shutil.copy(src, dest)
        clips.append({'file': name, 'start': 0.5, 'duration': 1.5, 'label': label, 'lut': lut})
    probe_data = probe.collect_probe(root)
    config = {
        'src': str(root),
        'out': str(root / 'SUMMARY_VIDEO.mp4'),
        'tmp': str(tmp),
        'frame': frame or {'shape': 'square', 'width': 320, 'height': 320, 'fps': 25.0},
        'quality': 60,
        'audio_br': '192k',
        'lut': str(common.LUT_PATH),
        'music': music,
        **extra,
    }
    return config, clips, probe_data


@pytest.fixture
def render_project():
    return build_render_project


@pytest.fixture(scope='session')
def rendered_project(tmp_path_factory, square_clip, vertical_clip, silent_clip):
    import render_summary

    base = tmp_path_factory.mktemp('rendered')
    project = base / 'trip'
    sources = [(square_clip, 'square.MP4', 'Harbour', True),
               (vertical_clip, 'vertical.MP4', 'Peak', False),
               (silent_clip, 'silent.MP4', 'Tram', False)]
    config, clips, probe_data = build_render_project(project, sources, base / 'tmp')
    (project / 'config.json').write_text(json.dumps(config))
    (project / 'clips.json').write_text(json.dumps(clips))
    (project / 'probe.json').write_text(json.dumps(probe_data))
    out = render_summary.render(config, clips, probe_data)
    return {
        'project': project,
        'config': config,
        'clips': clips,
        'out': out,
        'manifest': Path(config['tmp']) / 'render-manifest.json',
    }
