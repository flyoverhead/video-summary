import json
import subprocess
import sys
from pathlib import Path

import pytest

import project

SCRIPT = Path(__file__).resolve().parent.parent / 'video-summary' / 'scripts' / 'project.py'


def cli(*args, stdin=None):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], input=stdin,
                          capture_output=True, text=True)


def test_write_creates_json(tmp_path):
    status, diff = project.write(tmp_path, 'brief.json', '{"type": "trip"}')
    assert status == 'created' and diff == ''
    assert json.loads((tmp_path / 'brief.json').read_text()) == {'type': 'trip'}


def test_write_refuses_existing_and_returns_diff(tmp_path):
    project.write(tmp_path, 'brief.json', '{"type": "trip"}')
    status, diff = project.write(tmp_path, 'brief.json', '{"type": "sport"}')
    assert status == 'refused'
    assert '-  "type": "trip"' in diff and '+  "type": "sport"' in diff
    assert json.loads((tmp_path / 'brief.json').read_text()) == {'type': 'trip'}


def test_write_overwrite(tmp_path):
    project.write(tmp_path, 'clips.json', '[]')
    status, diff = project.write(tmp_path, 'clips.json', '[{"file": "a.MP4"}]', overwrite=True)
    assert status == 'overwritten' and '+' in diff
    assert json.loads((tmp_path / 'clips.json').read_text()) == [{'file': 'a.MP4'}]


def test_write_unchanged(tmp_path):
    project.write(tmp_path, 'config.json', '{"quality": 50}')
    assert project.write(tmp_path, 'config.json', '{ "quality" : 50 }') == ('unchanged', '')


def test_write_summary_text(tmp_path):
    status, _ = project.write(tmp_path, 'SUMMARY.md', '# Trip\n')
    assert status == 'created' and (tmp_path / 'SUMMARY.md').read_text() == '# Trip\n'


@pytest.mark.parametrize('name', ['probe.json', 'moments.json', 'SUMMARY_VIDEO.mp4', '../x.json', 'notes.txt'])
def test_write_rejects_other_names(tmp_path, name):
    with pytest.raises(ValueError):
        project.write(tmp_path, name, '{}')


def test_write_rejects_invalid_json(tmp_path):
    with pytest.raises(ValueError):
        project.write(tmp_path, 'brief.json', '{nope')
    assert not (tmp_path / 'brief.json').exists()


def test_cli_stdin_and_refusal(tmp_path):
    first = cli('write', tmp_path, 'brief.json', '-', stdin='{"type": "trip"}')
    assert first.returncode == 0 and 'created' in first.stdout
    second = cli('write', tmp_path, 'brief.json', '-', stdin='{"type": "sport"}')
    assert second.returncode == 1
    assert '+  "type": "sport"' in second.stdout and '--overwrite' in second.stderr
    third = cli('write', tmp_path, 'brief.json', '-', '--overwrite', stdin='{"type": "sport"}')
    assert third.returncode == 0 and 'overwritten' in third.stdout
    assert json.loads((tmp_path / 'brief.json').read_text()) == {'type': 'sport'}


def test_cli_source_file(tmp_path):
    src = tmp_path / 'in.json'
    src.write_text('[{"file": "a.MP4"}]')
    proj = tmp_path / 'p'
    proj.mkdir()
    assert cli('write', proj, 'clips.json', src).returncode == 0
    assert json.loads((proj / 'clips.json').read_text()) == [{'file': 'a.MP4'}]


def test_cli_errors(tmp_path):
    assert cli('write', tmp_path, 'probe.json', '-', stdin='{}').returncode == 2
    assert cli('write', tmp_path, 'brief.json', '-', stdin='{bad').returncode == 2
    assert cli('write', tmp_path / 'missing', 'brief.json', '-', stdin='{}').returncode == 2


def _render_inputs(root, music=None):
    root.mkdir(exist_ok=True)
    brief = {'type': 'trip', 'target_min': [10, 15]}
    config = {'src': str(root), 'out': str(root / 'SUMMARY_VIDEO.mp4'), 'tmp': '/tmp/x',
              'frame': {'shape': 'square', 'width': 2560, 'height': 2560, 'fps': 50.0},
              'quality': 60, 'audio_br': '192k', 'lut': None, 'music': music}
    clips = [{'file': 'a.MP4', 'start': 0, 'duration': 90.0, 'label': 'Harbour', 'lut': True},
             {'file': 'b.MP4', 'start': 5, 'duration': 30.0, 'label': 'Peak', 'lut': False}]
    for name, data in (('brief.json', brief), ('config.json', config), ('clips.json', clips)):
        (root / name).write_text(json.dumps(data))
    return root


def test_summary_fields(tmp_path):
    root = _render_inputs(tmp_path / 'trip')
    text = project.summary(root)
    for needle in ('trip', '2 clips', '2m 00s', 'square 2560x2560 @ 50', '1 of 2 (a.MP4)', 'none',
                   'standard (60)', str(root / 'SUMMARY_VIDEO.mp4'), '~8m 00s'):
        assert needle in text, needle


def test_summary_music_and_existing_output(tmp_path):
    root = _render_inputs(tmp_path / 'trip', music={'file': '/m/song.mp3', 'mode': 'duck', 'duck_db': -18})
    (root / 'SUMMARY_VIDEO.mp4').write_bytes(b'x' * 10)
    text = project.summary(root)
    assert 'duck (/m/song.mp3)' in text
    assert 'exists' in text


def test_cli_summary(tmp_path):
    root = _render_inputs(tmp_path / 'trip')
    proc = cli('summary', root)
    assert proc.returncode == 0 and '2 clips' in proc.stdout


def test_summary_lists_fitted_clips(tmp_path):
    root = _render_inputs(tmp_path / 'trip')
    probe = {'clips': [{'file': 'a.MP4', 'width': 3840, 'height': 3840},
                       {'file': 'b.MP4', 'width': 1920, 'height': 1080}]}
    (root / 'probe.json').write_text(json.dumps(probe))
    assert 'Fitted:    1 clip with blurred fill (b.MP4 wide)' in project.summary(root)


def test_summary_names_quality_presets(tmp_path):
    root = _render_inputs(tmp_path / 'trip')
    for value, name in ((40, 'draft'), (60, 'standard'), (75, 'high'), (50, 'custom')):
        config = json.loads((root / 'config.json').read_text())
        config['quality'] = value
        (root / 'config.json').write_text(json.dumps(config))
        assert f'Quality:   {name} ({value})' in project.summary(root)


def _sheet_project(render_project, tmp_path, n, wide_clip, square_clip):
    sources = [(square_clip if i % 2 == 0 else wide_clip, 'a.MP4' if i % 2 == 0 else 'b.MP4', f'Clip {i}', i == 0)
               for i in range(n)]
    config, clips, probe_data = render_project(tmp_path / 'trip', sources, tmp_path / 'tmp')
    root = tmp_path / 'trip'
    (root / 'probe.json').write_text(json.dumps(probe_data))
    return root, clips


def _width(path):
    from common import run
    out = run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
               '-of', 'csv=p=0', str(path)]).stdout.strip()
    return tuple(int(v) for v in out.split(','))


def test_sheet_one_page(render_project, tmp_path, wide_clip, square_clip):
    root, clips = _sheet_project(render_project, tmp_path, 3, wide_clip, square_clip)
    pages = project.contact_sheet(root, clips)
    assert [p.name for p in pages] == ['contact-sheet-01.png']
    assert _width(pages[0]) == (6 * 320, 8 * 320)


def test_sheet_pages_split(render_project, tmp_path, square_clip):
    root, clips = _sheet_project(render_project, tmp_path, 1, square_clip, square_clip)
    pages = project.contact_sheet(root, clips * 49)
    assert [p.name for p in pages] == ['contact-sheet-01.png', 'contact-sheet-02.png']
    assert all(_width(p)[0] == 6 * 320 for p in pages)


def test_sheet_stale_pages_removed(render_project, tmp_path, square_clip):
    root, clips = _sheet_project(render_project, tmp_path, 1, square_clip, square_clip)
    assert len(project.contact_sheet(root, clips * 49)) == 2
    pages = project.contact_sheet(root, clips)
    assert [p.name for p in pages] == ['contact-sheet-01.png']
    assert not (pages[0].parent / 'contact-sheet-02.png').exists()


def test_sheet_frame_cache_reused(render_project, tmp_path, wide_clip, square_clip):
    root, clips = _sheet_project(render_project, tmp_path, 3, wide_clip, square_clip)
    pages = project.contact_sheet(root, clips)
    frames = sorted((pages[0].parent / 'frames').glob('*.jpg'))
    assert len(frames) == 3
    before = {f: f.stat().st_mtime_ns for f in frames}
    project.contact_sheet(root, clips)
    after = sorted((pages[0].parent / 'frames').glob('*.jpg'))
    assert after == frames and {f: f.stat().st_mtime_ns for f in after} == before


def test_sheet_writes_nothing_in_project(render_project, tmp_path, wide_clip, square_clip):
    root, clips = _sheet_project(render_project, tmp_path, 3, wide_clip, square_clip)
    snapshot = sorted(p.relative_to(root) for p in root.rglob('*'))
    project.contact_sheet(root, clips)
    assert sorted(p.relative_to(root) for p in root.rglob('*')) == snapshot


def test_sheet_cli_stdin_and_error(render_project, tmp_path, wide_clip, square_clip):
    root, clips = _sheet_project(render_project, tmp_path, 2, wide_clip, square_clip)
    done = cli('sheet', root, '-', stdin=json.dumps(clips))
    assert done.returncode == 0 and done.stdout.strip().endswith('contact-sheet-01.png')
    bad = cli('sheet', root, '-', stdin=json.dumps([{'file': 'nope.MP4', 'start': 0, 'duration': 1}]))
    assert bad.returncode == 2 and bad.stderr.startswith('ERROR:')


def test_clean_removes_only_project_cache(tmp_path):
    import common
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir()
    b.mkdir()
    (a / 'brief.json').write_text('{}')
    cache_a, cache_b = common.cache_dir(a), common.cache_dir(b)
    (cache_a / 'x.bin').write_bytes(b'x' * 1000)
    (cache_b / 'y.bin').write_bytes(b'y')
    path, freed = project.clean_cache(a)
    assert path == cache_a.resolve() and freed == 1000
    assert not cache_a.exists()
    assert (cache_b / 'y.bin').exists()
    assert (a / 'brief.json').exists()


def test_clean_without_cache(tmp_path):
    import common
    proj = tmp_path / 'p'
    proj.mkdir()
    result = cli('clean', proj)
    assert result.returncode == 0 and 'no cache' in result.stdout
    assert not any(common.CACHE_ROOT.iterdir()) if common.CACHE_ROOT.exists() else True


def test_clean_cli_reports_removed(tmp_path):
    import common
    proj = tmp_path / 'p'
    proj.mkdir()
    (common.cache_dir(proj) / 'x.bin').write_bytes(b'x')
    result = cli('clean', proj)
    assert result.returncode == 0 and result.stdout.startswith('removed ') and 'MB)' in result.stdout


def test_clean_refuses_path_outside_cache_root(tmp_path):
    import common
    proj = tmp_path / 'p'
    proj.mkdir()
    victim = tmp_path / 'victim'
    victim.mkdir()
    (victim / 'keep.txt').write_text('k')
    common.CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    (common.CACHE_ROOT / common.cache_slug(proj)).symlink_to(victim)
    with pytest.raises(ValueError):
        project.clean_cache(proj)
    assert (victim / 'keep.txt').exists()


def _cache_with_manifest(proj):
    import common
    cache = common.cache_dir(proj)
    (cache / 'thumbs').mkdir()
    (cache / 'thumbs' / 't.jpg').write_bytes(b't' * 10)
    (cache / 'transcripts').mkdir()
    (cache / 'transcripts' / 'a.json').write_text('{}')
    (cache / 'render').mkdir()
    (cache / 'render' / 'clip_001.mp4').write_bytes(b'v' * 100)
    manifest = cache / 'render' / 'render-manifest.final.json'
    manifest.write_text('{"clips": []}')
    return cache, manifest


def test_clean_keeps_render_manifest(tmp_path):
    proj = tmp_path / 'p'
    proj.mkdir()
    cache, manifest = _cache_with_manifest(proj)
    path, freed = project.clean_cache(proj)
    assert freed == 10 + 2 + 100
    assert sorted(p.relative_to(cache).as_posix() for p in cache.rglob('*')) == ['render', 'render/render-manifest.final.json']
    assert manifest.read_text() == '{"clips": []}'


def test_clean_cli_reports_kept_manifest(tmp_path):
    proj = tmp_path / 'p'
    proj.mkdir()
    _cache_with_manifest(proj)
    result = cli('clean', proj)
    assert result.returncode == 0 and result.stdout.rstrip().endswith('MB), kept render manifest')


def test_clean_without_manifest_removes_folder(tmp_path):
    import common
    proj = tmp_path / 'p'
    proj.mkdir()
    cache = common.cache_dir(proj)
    (cache / 'render').mkdir()
    (cache / 'render' / 'clip_001.mp4').write_bytes(b'v')
    project.clean_cache(proj)
    assert not cache.exists()


def test_clean_refuses_symlink_to_sibling_cache(tmp_path):
    import common
    proj = tmp_path / 'p'
    proj.mkdir()
    sibling = common.cache_dir(tmp_path / 'other')
    (sibling / 'keep.bin').write_bytes(b'k')
    (common.CACHE_ROOT / common.cache_slug(proj)).symlink_to(sibling)
    with pytest.raises(ValueError):
        project.clean_cache(proj)
    assert (sibling / 'keep.bin').exists()


def test_clean_does_not_follow_symlinked_render_dir(tmp_path):
    import common
    proj = tmp_path / 'p'
    proj.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'render-manifest.x.json').write_text('{}')
    (outside / 'precious.mp4').write_bytes(b'p')
    cache = common.cache_dir(proj)
    (cache / 'x.bin').write_bytes(b'x')
    (cache / 'render').symlink_to(outside)
    project.clean_cache(proj)
    assert (outside / 'render-manifest.x.json').exists() and (outside / 'precious.mp4').exists()
    assert not (cache / 'render').exists() and not (cache / 'render').is_symlink()
