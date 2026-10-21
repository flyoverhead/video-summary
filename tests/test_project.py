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
