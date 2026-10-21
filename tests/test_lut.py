import json
import subprocess
import sys
from pathlib import Path

import pytest

from common import LUT_PATH, read_json, run, write_output
from lut import camera_source, detect, escape_filter_path, parse_decisions, preview, set_decisions, show
from sample import extract_thumb


def _thumb(clip, tmp_path, name='t.jpg'):
    return extract_thumb(clip, 1.0, tmp_path / name, 320)


def _size(path):
    out = run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
               'stream=width,height', '-of', 'json', str(path)]).stdout
    s = json.loads(out)['streams'][0]
    return s['width'], s['height']


def test_preview_double_width(square_clip, tmp_path):
    out = preview(square_clip, 1.0, tmp_path / 'p.jpg')
    assert _size(out) == (640, 320)


def test_preview_lut_path_with_specials(square_clip, tmp_path):
    odd = tmp_path / "we ird: 'dir"
    odd.mkdir()
    lut = odd / 'a b.cube'
    lut.write_bytes(LUT_PATH.read_bytes())
    out = preview(square_clip, 1.0, tmp_path / 'p2.jpg', lut=lut)
    assert _size(out) == (640, 320)


def test_escape_filter_path():
    assert escape_filter_path("/a b/c:d'e") == "/a b/c\\\\:d\\\\\\'e"


def test_camera_source():
    dji = [{'codec_type': 'video', 'codec_tag_string': 'hvc1'}, {'codec_type': 'data', 'codec_tag_string': 'djmd'}]
    phone = [{'codec_type': 'video', 'codec_tag_string': 'hvc1'}, {'codec_type': 'data', 'codec_tag_string': 'tmcd'}]
    assert camera_source(dji) == 'dji'
    assert camera_source(phone) == 'other'
    assert camera_source([]) == 'other'


def test_detect_reports_every_clip_unknown(project):
    import probe
    write_output(project, 'probe.json', probe.collect_probe(project))
    assert detect(project) == {'22.08/square.MP4': ('unknown', 'other'), '22.08/wide.MP4': ('unknown', 'other'),
                               '25.08/vertical.MP4': ('unknown', 'other')}


def test_cli_detect_lines(project):
    import probe
    write_output(project, 'probe.json', probe.collect_probe(project))
    proc = lut_cli(project, 'detect')
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == ['unknown  other  22.08/square.MP4', 'unknown  other  22.08/wide.MP4',
                                        'unknown  other  25.08/vertical.MP4']


LUT_SCRIPT = Path(__file__).resolve().parent.parent / 'video-summary' / 'scripts' / 'lut.py'
SET_PROBE = {'clips': [{'file': 'd1/a.MP4'}, {'file': 'd1/b.MP4'}, {'file': 'd2/c.MP4'}]}


def _set_project(tmp_path, clips=None):
    write_output(tmp_path, 'probe.json', SET_PROBE)
    write_output(tmp_path, 'moments.json', {'candidates': [], 'scores': {'c1': {}}, 'lut': {'d1/a.MP4': False}})
    if clips is not None:
        write_output(tmp_path, 'clips.json', clips)


def _clip(file, lut):
    return {'file': file, 'start': 0.0, 'duration': 2.0, 'label': 'X', 'lut': lut}


def test_set_records_moments_and_keeps_keys(tmp_path):
    _set_project(tmp_path)
    set_decisions(tmp_path, {'d1/a.MP4': True, 'd2/c.MP4': False})
    out = read_json(tmp_path / 'moments.json')
    assert out['lut'] == {'d1/a.MP4': True, 'd2/c.MP4': False}
    assert out['scores'] == {'c1': {}}
    assert not (tmp_path / 'clips.json').exists()


def test_set_updates_clips_flags(tmp_path):
    _set_project(tmp_path, [_clip('d1/a.MP4', False), _clip('d1/b.MP4', True), _clip('d1/a.MP4', False)])
    set_decisions(tmp_path, {'d1/a.MP4': True})
    clips = read_json(tmp_path / 'clips.json')
    assert [c['lut'] for c in clips] == [True, True, True]


def test_set_rejects_unknown_file(tmp_path):
    _set_project(tmp_path)
    with pytest.raises(ValueError) as exc:
        set_decisions(tmp_path, {'nope.MP4': True})
    assert 'nope.MP4' in str(exc.value)
    assert read_json(tmp_path / 'moments.json')['lut'] == {'d1/a.MP4': False}


def test_parse_decisions():
    assert parse_decisions(['d1/a.MP4=true', 'x y.MP4=false'], None, ['q']) == {'d1/a.MP4': True, 'x y.MP4': False}
    assert parse_decisions(['d1/a.MP4=false'], True, ['d1/a.MP4', 'b']) == {'d1/a.MP4': False, 'b': True}
    with pytest.raises(ValueError):
        parse_decisions(['d1/a.MP4=yes'], None, [])
    with pytest.raises(ValueError):
        parse_decisions([], None, [])


def lut_cli(*args):
    return subprocess.run([sys.executable, str(LUT_SCRIPT), *map(str, args)], capture_output=True, text=True)


def test_cli_set_all_and_override(tmp_path):
    _set_project(tmp_path, [_clip('d2/c.MP4', False)])
    proc = lut_cli(tmp_path, 'set', '--all', 'true', 'd1/b.MP4=false')
    assert proc.returncode == 0, proc.stderr
    assert read_json(tmp_path / 'moments.json')['lut'] == {'d1/a.MP4': True, 'd1/b.MP4': False, 'd2/c.MP4': True}
    assert read_json(tmp_path / 'clips.json')[0]['lut'] is True
    assert lut_cli(tmp_path, 'set', 'ghost.MP4=true').returncode == 1


def test_show_lists_every_clip_absent_is_off(tmp_path):
    _set_project(tmp_path)
    lines, mismatches = show(tmp_path)
    assert lines == ['off  d1/a.MP4', 'off  d1/b.MP4', 'off  d2/c.MP4']
    assert mismatches == []
    set_decisions(tmp_path, {'d2/c.MP4': True})
    assert show(tmp_path)[0] == ['off  d1/a.MP4', 'off  d1/b.MP4', 'on   d2/c.MP4']


def test_show_reports_clips_mismatch(tmp_path):
    _set_project(tmp_path, [_clip('d1/a.MP4', False), _clip('d1/b.MP4', True)])
    assert show(tmp_path)[1] == ['clip 1 d1/b.MP4: clips.json lut true, moments.json false']


def test_cli_show_exit_codes(tmp_path):
    _set_project(tmp_path, [_clip('d1/a.MP4', False)])
    proc = lut_cli(tmp_path, 'show')
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == ['off  d1/a.MP4', 'off  d1/b.MP4', 'off  d2/c.MP4', 'clips.json: 1 clips match']
    write_output(tmp_path, 'clips.json', [_clip('d1/a.MP4', True)], overwrite=True)
    proc = lut_cli(tmp_path, 'show')
    assert proc.returncode == 1
    assert 'clip 0 d1/a.MP4: clips.json lut true, moments.json false' in proc.stdout


def test_cli_detect_without_probe_is_clean_error(tmp_path):
    proc = lut_cli(tmp_path, 'detect')
    assert proc.returncode == 1
    assert proc.stderr.startswith('ERROR:') and 'Traceback' not in proc.stderr


def test_cli_show_malformed_clips_is_clean_error(tmp_path):
    _set_project(tmp_path, [{'start': 0.0}])
    proc = lut_cli(tmp_path, 'show')
    assert proc.returncode == 1
    assert proc.stderr.startswith('ERROR:') and 'Traceback' not in proc.stderr
    write_output(tmp_path, 'clips.json', ['oops'], overwrite=True)
    proc = lut_cli(tmp_path, 'show')
    assert proc.returncode == 1
    assert proc.stderr.startswith('ERROR:') and 'Traceback' not in proc.stderr
