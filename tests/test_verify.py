import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import verify


@pytest.fixture
def copy_project(rendered_project, tmp_path):
    dest = tmp_path / 'trip'
    shutil.copytree(rendered_project['project'], dest)
    tmp = tmp_path / 'tmp'
    shutil.copytree(rendered_project['config']['tmp'], tmp)
    config = json.loads((dest / 'config.json').read_text())
    config.update(src=str(dest), out=str(dest / 'SUMMARY_VIDEO.mp4'), tmp=str(tmp))
    (dest / 'config.json').write_text(json.dumps(config))
    return dest


def _edit(path, fn):
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data))


def test_verify_ok_after_render(rendered_project):
    assert verify.verify(rendered_project['project']) == []


def test_verify_flags_duration_mismatch(copy_project):
    _edit(copy_project / 'clips.json', lambda c: c[0].update(duration=c[0]['duration'] + 10))
    problems = verify.verify(copy_project)
    assert any('duration' in p for p in problems)


def test_verify_flags_lut_mismatch(copy_project):
    _edit(copy_project / 'clips.json', lambda c: c[1].update(lut=True))
    assert any('LUT' in p for p in verify.verify(copy_project))


def test_verify_flags_file_list_mismatch(copy_project):
    _edit(copy_project / 'clips.json', lambda c: c.pop())
    assert any('file list' in p for p in verify.verify(copy_project))


def test_verify_flags_missing_output(copy_project):
    (copy_project / 'SUMMARY_VIDEO.mp4').unlink()
    assert any('missing' in p for p in verify.verify(copy_project))


def test_verify_flags_size_mismatch(copy_project):
    _edit(copy_project / 'config.json', lambda c: c['frame'].update(width=640, height=640))
    assert any('dimensions' in p for p in verify.verify(copy_project))


def test_verify_draft_expected_size(rendered_project, copy_project):
    import render_summary
    config = json.loads((copy_project / 'config.json').read_text())
    clips = json.loads((copy_project / 'clips.json').read_text())
    probe = json.loads((copy_project / 'probe.json').read_text())
    config['draft_long_side'] = 160
    (copy_project / 'config.json').write_text(json.dumps(config))
    render_summary.render(config, clips, probe, draft=True)
    assert verify.verify(copy_project, draft=True) == []


def test_validate_ok(rendered_project):
    assert verify.validate_project(rendered_project['project']) == []


def test_validate_missing_files(tmp_path):
    problems = verify.validate_project(tmp_path)
    assert len(problems) == 3


def test_validate_out_of_range_trim(copy_project):
    _edit(copy_project / 'clips.json', lambda c: c[0].update(start=2.9))
    assert any('exceeds' in p for p in verify.validate_project(copy_project))


def test_validate_placeholder_and_missing_file(copy_project):
    _edit(copy_project / 'clips.json', lambda c: c[0].update(file='YYYYMMDD_x.MP4'))
    problems = verify.validate_project(copy_project)
    assert any('YYYYMMDD' in p for p in problems)
    assert any('not found' in p for p in problems)


def test_validate_out_not_in_root(copy_project):
    _edit(copy_project / 'config.json', lambda c: c.update(out=str(copy_project / 'sub' / 'x.mp4')))
    assert any('project root' in p for p in verify.validate_project(copy_project))


def test_validate_empty_clips(copy_project):
    (copy_project / 'clips.json').write_text('[]')
    assert any('empty' in p for p in verify.validate_project(copy_project))


def test_validate_out_name_not_allowlisted(copy_project):
    _edit(copy_project / 'config.json', lambda c: c.update(out=str(copy_project / 'square.MP4')))
    problems = verify.validate_project(copy_project)
    assert any('SUMMARY_VIDEO.mp4' in p for p in problems)


def test_validate_out_listed_in_probe(copy_project):
    _edit(copy_project / 'probe.json', lambda p: p['clips'].append({**p['clips'][0], 'file': 'SUMMARY_VIDEO.mp4'}))
    assert any('source clip' in p for p in verify.validate_project(copy_project))


def test_validate_src_not_project(copy_project, tmp_path):
    _edit(copy_project / 'config.json', lambda c: c.update(src=str(tmp_path / 'elsewhere')))
    assert any('config.src' in p for p in verify.validate_project(copy_project))


def test_validate_tmp_inside_source(copy_project):
    _edit(copy_project / 'config.json', lambda c: c.update(tmp=str(copy_project / 'render')))
    assert any('tmp' in p for p in verify.validate_project(copy_project))


def test_validate_file_not_in_probe(copy_project):
    (copy_project / 'extra.MP4').write_bytes((copy_project / 'square.MP4').read_bytes())
    _edit(copy_project / 'clips.json', lambda c: c[0].update(file='extra.MP4'))
    assert any('not in probe.json' in p for p in verify.validate_project(copy_project))


@pytest.mark.parametrize('name, fn', [
    ('clips.json', lambda c: c.__setitem__(0, 'oops')),
    ('clips.json', lambda c: c[0].pop('start')),
    ('clips.json', lambda c: c[0].update(start='zero')),
    ('clips.json', lambda c: c[0].update(duration=0)),
    ('clips.json', lambda c: c[0].update(start=-1)),
    ('clips.json', lambda c: c[0].update(file=None)),
    ('config.json', lambda c: c.pop('out')),
    ('config.json', lambda c: c.pop('tmp')),
    ('probe.json', lambda p: p.pop('clips')),
    ('probe.json', lambda p: p['clips'][0].pop('duration')),
])
def test_validate_malformed_reports_not_raises(copy_project, name, fn):
    _edit(copy_project / name, fn)
    problems = verify.validate_project(copy_project)
    assert problems and all(isinstance(p, str) for p in problems)


@pytest.mark.parametrize('name, text', [('clips.json', '{"a": 1}'), ('config.json', '[]'), ('probe.json', '[]')])
def test_validate_wrong_top_level_type(copy_project, name, text):
    (copy_project / name).write_text(text)
    assert any(name in p for p in verify.validate_project(copy_project))


VERIFY = Path(verify.__file__)


def _cli(*args):
    return subprocess.run([sys.executable, str(VERIFY), *map(str, args)], capture_output=True, text=True)


def test_cli_prints_path_duration_size_ok(rendered_project):
    proc = _cli(rendered_project['project'])
    assert proc.returncode == 0, proc.stdout
    lines = proc.stdout.splitlines()
    assert lines[0] == f'Output:   {rendered_project["out"]}'
    assert lines[1].startswith('Duration: 0m 04s (4.')
    assert lines[2].startswith('Size:') and lines[2].endswith('MB')
    assert lines[-1] == 'OK'


def test_cli_reports_problems(copy_project):
    _edit(copy_project / 'clips.json', lambda c: c[1].update(lut=True))
    proc = _cli(copy_project)
    assert proc.returncode == 1
    assert 'Size:' in proc.stdout and 'PROBLEM: manifest LUT flags differ from clips.json' in proc.stdout


def test_cli_missing_output(copy_project):
    (copy_project / 'SUMMARY_VIDEO.mp4').unlink()
    proc = _cli(copy_project)
    assert proc.returncode == 1
    assert f'Output:   {copy_project / "SUMMARY_VIDEO.mp4"}' in proc.stdout
    assert 'PROBLEM: output missing or empty' in proc.stdout


def test_cli_malformed_config_reports(copy_project):
    _edit(copy_project / 'config.json', lambda c: c.pop('frame'))
    proc = _cli(copy_project)
    assert proc.returncode == 1 and 'Traceback' not in proc.stderr
    assert 'PROBLEM:' in proc.stdout
