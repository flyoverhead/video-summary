import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'video-summary' / 'scripts'))

import common  # noqa: E402


def test_ffmpeg_env_prepends_full_bin():
    assert common.ffmpeg_env()['PATH'].startswith('/opt/homebrew/opt/ffmpeg-full/bin:')


def test_write_output_rejects_unknown_name(tmp_path):
    with pytest.raises(ValueError):
        common.write_output(tmp_path, 'notes.txt', 'x')


def test_write_output_refuses_existing(tmp_path):
    common.write_output(tmp_path, 'clips.json', [])
    with pytest.raises(FileExistsError):
        common.write_output(tmp_path, 'clips.json', [])
    common.write_output(tmp_path, 'clips.json', [1], overwrite=True)
    assert common.read_json(tmp_path / 'clips.json') == [1]


def test_write_output_text(tmp_path):
    path = common.write_output(tmp_path, 'SUMMARY.md', 'raw')
    assert path.read_text() == 'raw'


def test_output_path_allows_only_summary_videos(tmp_path):
    assert common.output_path(tmp_path, 'SUMMARY_VIDEO.mp4') == tmp_path / 'SUMMARY_VIDEO.mp4'
    assert common.output_path(tmp_path, 'SUMMARY_VIDEO.draft.mp4') == tmp_path / 'SUMMARY_VIDEO.draft.mp4'


@pytest.mark.parametrize('name', ['sub/x.mp4', 'DJI_0001_D.mp4', 'clip.MP4', 'summary_video.mp4',
                                  '../SUMMARY_VIDEO.mp4', 'SUMMARY_VIDEO.mov'])
def test_output_path_rejects_other_videos(tmp_path, name):
    with pytest.raises(ValueError):
        common.output_path(tmp_path, name)


@pytest.mark.parametrize('name', ['brief.json', 'probe.json', 'moments.json', 'clips.json', 'config.json',
                                  'SUMMARY.md'])
def test_output_path_accepts_required_names(tmp_path, name):
    assert common.output_path(tmp_path, name) == tmp_path / name


@pytest.mark.parametrize('name', ['analysis.json', 'analysis.md', 'contact_sheet.jpg', 'verify_report.json'])
def test_output_path_rejects_other_names(tmp_path, name):
    with pytest.raises(ValueError):
        common.output_path(tmp_path, name)


def test_allowed_outputs_exact():
    assert common.ALLOWED_OUTPUTS == {'brief.json', 'probe.json', 'moments.json', 'clips.json', 'config.json',
                                      'SUMMARY.md'}


def test_cache_dir_outside_project(monkeypatch, tmp_path):
    monkeypatch.setattr(common, 'CACHE_ROOT', tmp_path.parent / (tmp_path.name + '-cache'))
    cache = common.cache_dir(tmp_path)
    assert cache.is_dir()
    assert tmp_path not in cache.parents


def test_cache_dir_slug_relative_to_camera(monkeypatch, tmp_path):
    monkeypatch.setattr(common, 'CAMERA_ROOT', tmp_path / 'camera')
    monkeypatch.setattr(common, 'CACHE_ROOT', tmp_path / 'cache')
    project = tmp_path / 'camera' / 'trip' / 'day 1'
    project.mkdir(parents=True)
    assert common.cache_dir(project) == tmp_path / 'cache' / 'trip-day 1'


def test_lut_bundled():
    assert common.LUT_PATH.exists()
    lines = [ln for ln in common.LUT_PATH.read_text().splitlines() if ln.strip() and not ln.startswith('#')]
    assert lines[0] == 'LUT_3D_SIZE 33'


def test_defaults_keys():
    d = common.defaults()
    assert {'sampling', 'types', 'render'} <= d.keys()
    assert 'lut' not in d


def test_fixtures_build(square_clip, wide_clip, vertical_clip, cut_clip, loud_clip, short_clip,
                        silent_clip):
    for clip in (square_clip, wide_clip, vertical_clip, cut_clip, loud_clip, short_clip, silent_clip):
        assert clip.stat().st_size > 0


def test_fixture_geometry(square_clip, wide_clip, vertical_clip, silent_clip):
    def probe(p, entries):
        out = common.run(['ffprobe', '-v', 'error', '-show_entries', entries, '-of', 'csv=p=0', str(p)])
        return out.stdout.strip()

    assert probe(square_clip, 'stream=width,height,codec_name').splitlines()[0] == 'hevc,320,320'
    assert probe(wide_clip, 'stream=width,height').splitlines()[0] == '480,270'
    assert probe(vertical_clip, 'stream=width,height').splitlines()[0] == '270,480'
    streams = common.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0',
                          str(silent_clip)]).stdout.split()
    assert streams == ['video']


def test_project_fixture(project):
    assert (project / '22.08' / 'square.MP4').exists()
    assert (project / '25.08' / 'vertical.MP4').exists()
    assert list(project.glob('*/*.LRF'))
    assert ' ' in project.name


def test_cache_dir_distinct_for_same_name_outside_camera(monkeypatch, tmp_path):
    monkeypatch.setattr(common, 'CAMERA_ROOT', tmp_path / 'camera')
    monkeypatch.setattr(common, 'CACHE_ROOT', tmp_path / 'cache')
    a, b = tmp_path / 'x' / 'trip', tmp_path / 'y' / 'trip'
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    ca, cb = common.cache_dir(a), common.cache_dir(b)
    assert ca != cb
    assert ca.name.startswith('trip-') and cb.name.startswith('trip-')
    assert common.cache_dir(a) == ca
