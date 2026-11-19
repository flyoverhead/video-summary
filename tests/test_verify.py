import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import verify
from common import defaults, run


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


def test_verify_pilot_draft_ok(copy_project):
    import render_summary
    config = json.loads((copy_project / 'config.json').read_text())
    clips = json.loads((copy_project / 'clips.json').read_text())
    probe = json.loads((copy_project / 'probe.json').read_text())
    render_summary.render(config, clips, probe, draft=True, clip_range=(2, 3))
    assert verify.verify(copy_project, draft=True) == []
    _edit(copy_project / 'clips.json', lambda c: c[2].update(lut=True))
    assert any('LUT' in p for p in verify.verify(copy_project, draft=True))


def test_verify_missing_manifest(copy_project):
    (Path(json.loads((copy_project / 'config.json').read_text())['tmp']) / 'render-manifest.final.json').unlink()
    assert any('manifest missing' in p for p in verify.verify(copy_project))


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
    proc = _cli(rendered_project['project'], '--no-qa')
    assert proc.returncode == 0, proc.stdout
    lines = proc.stdout.splitlines()
    assert lines[0] == f'Output:   {rendered_project["out"]}'
    assert lines[1].startswith('Duration: 0m 04s (4.')
    assert lines[2].startswith('Size:') and lines[2].endswith('MB')
    assert lines[-1] == 'OK'


def test_cli_reports_problems(copy_project):
    _edit(copy_project / 'clips.json', lambda c: c[1].update(lut=True))
    proc = _cli(copy_project, '--no-qa')
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


@pytest.mark.parametrize('text, expected', [
    ('7', 7.0), ('7.5', 7.5), ('3:41', 221.0), ('3:41.5', 221.5), ('1:02:03', 3723.0), ('0:00.25', 0.25),
])
def test_parse_time_forms(text, expected):
    assert verify.parse_time(text) == expected


@pytest.mark.parametrize('text', ['', 'x:yz', '-5', '1:75', '1:2:3:4', '3:4', '1.2.3', ' 7'])
def test_parse_time_rejects(text):
    with pytest.raises(ValueError):
        verify.parse_time(text)


def test_format_location_exact_example():
    loc = {'number': 19, 'file': '22.08/DJI_0031_D.MP4', 'source_t': 34.2, 'clip_start': 30.0,
           'clip_end': 38.0, 'offset': 4.2, 'label': 'Night Market'}
    assert verify.format_location(221, loc) == \
        '3:41 → #19 22.08/DJI_0031_D.MP4 @ 34.2s (clip 30.0→38.0, 0:04 into it) "Night Market"'
    assert verify.format_location(221.5, loc).startswith('3:41.5 → ')
    assert verify.format_location(3723, loc).startswith('1:02:03 → ')


def test_format_location_floors_offset_despite_float_error():
    loc = {'number': 1, 'file': 'a.MP4', 'source_t': 3.0, 'clip_start': 0.0, 'clip_end': 8.0,
           'offset': 3 - 1e-9, 'label': 'x'}
    assert '0:03 into it' in verify.format_location(3, loc)
    assert '1:00 into it' in verify.format_location(60, {**loc, 'offset': 60 - 1e-9})


def test_locate_maps_into_second_clip(rendered_project):
    manifest = json.loads(rendered_project['manifest'].read_text())
    first, second = manifest['clips'][0], manifest['clips'][1]
    loc = verify.locate(manifest, verify.clip_length(first) + 0.4)
    assert loc['number'] == 2 and loc['file'] == second['file'] and loc['label'] == second['label']
    assert loc['source_t'] == pytest.approx(second['start'] + 0.4)
    assert loc['clip_start'] == second['start']
    assert loc['clip_end'] == pytest.approx(second['start'] + second['duration'])
    assert loc['offset'] == pytest.approx(0.4)


def test_locate_boundaries(rendered_project):
    manifest = json.loads(rendered_project['manifest'].read_text())
    clips = manifest['clips']
    assert verify.locate(manifest, 0)['number'] == 1
    assert verify.locate(manifest, verify.clip_length(clips[0]))['number'] == 2
    total = verify.manifest_total(manifest)
    assert verify.locate(manifest, total)['number'] == len(clips)
    assert verify.locate(manifest, total + 0.01) is None


def test_locate_pilot_uses_range_numbers(copy_project):
    import render_summary
    config = json.loads((copy_project / 'config.json').read_text())
    clips = json.loads((copy_project / 'clips.json').read_text())
    probe = json.loads((copy_project / 'probe.json').read_text())
    render_summary.render(config, clips, probe, draft=True, clip_range=(2, 3))
    manifest = json.loads((Path(config['tmp']) / 'render-manifest.draft.json').read_text())
    assert verify.locate(manifest, 0.2)['number'] == 2
    assert verify.locate(manifest, clips[1]['duration'] + 0.2)['number'] == 3


def test_locate_out_of_range_and_malformed(rendered_project):
    manifest = json.loads(rendered_project['manifest'].read_text())
    total = sum(c['duration'] for c in manifest['clips'])
    lines, ok = verify.locate_lines(manifest, ['0:01', '99:00', 'x:yz'])
    assert not ok
    assert lines[0].startswith('0:01 → #1 ')
    assert lines[1] == f'99:00 → past the end ({verify.format_clock(total, False)})'
    assert lines[2] == 'x:yz → ERROR: not a time'


def test_cli_locate(rendered_project):
    proc = _cli(rendered_project['project'], '--locate', '0:01', 'x:yz', '99:00')
    assert proc.returncode == 1
    lines = proc.stdout.splitlines()
    assert len(lines) == 3 and lines[0].startswith('0:01 → #1 ') and 'Duration' not in proc.stdout
    ok = _cli(rendered_project['project'], '--locate', '1')
    assert ok.returncode == 0 and ok.stdout.startswith('0:01 → #1 ')


def test_cli_locate_missing_manifest(copy_project):
    manifest = Path(json.loads((copy_project / 'config.json').read_text())['tmp']) / 'render-manifest.final.json'
    manifest.unlink()
    proc = _cli(copy_project, '--locate', '1')
    assert proc.returncode == 1
    assert proc.stdout.strip() == f'ERROR: render manifest missing: {manifest}'



def test_cli_locate_negative_times_are_times(rendered_project):
    proc = _cli(rendered_project['project'], '--locate', '0:05', '-5', '-1:00')
    assert proc.returncode == 1, proc.stderr
    lines = proc.stdout.splitlines()
    assert len(lines) == 3
    assert lines[1:] == ['-5 → ERROR: not a time', '-1:00 → ERROR: not a time']


def test_cli_locate_corrupt_manifest(copy_project):
    manifest = Path(json.loads((copy_project / 'config.json').read_text())['tmp']) / 'render-manifest.final.json'
    manifest.write_text('{bad')
    proc = _cli(copy_project, '--locate', '1')
    assert proc.returncode == 1
    assert proc.stdout.startswith(f'ERROR: cannot read render manifest {manifest}: ')
    assert 'Traceback' not in proc.stderr

QA = defaults()['qa']
QA_SCAN_SCRIPT = (
    'testsrc2=s=160x90:r=25:d=2[a];color=c=black:s=160x90:r=25:d=1[b];color=c=green:s=160x90:r=25:d=3.5[c];'
    'testsrc2=s=160x90:r=25:d=2,hue=h=120[d];color=c=red:s=160x90:r=25:d=0.1[e];'
    'testsrc2=s=160x90:r=25:d=2,hue=h=240[f];[a][b][c][d][e][f]concat=n=6:v=1:a=0')


@pytest.fixture(scope='session')
def qa_clip(tmp_path_factory):
    path = tmp_path_factory.mktemp('qa') / 'qa.mp4'
    run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', QA_SCAN_SCRIPT,
         '-f', 'lavfi', '-i', "aevalsrc='0.3*sin(2*PI*440*t)*not(between(t,3,6.5))':s=48000:d=10.6",
         '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(path)])
    return path


@pytest.fixture(scope='session')
def qa_log(qa_clip):
    return verify.qa_scan(qa_clip, QA)


def _span(spans, start, end):
    return any(s == pytest.approx(start, abs=0.1) and e == pytest.approx(end, abs=0.1) for s, e in spans)


def test_parse_qa_reads_filters(qa_log):
    parsed = verify.parse_qa(qa_log)
    assert _span(parsed['black'], 2.0, 3.0)
    assert _span(parsed['freeze'], 3.0, 6.5)
    assert _span(parsed['silence'], 3.0, 6.5)
    assert any(abs(c - 8.52) < 0.1 for c in parsed['cuts']) and any(abs(c - 8.64) < 0.1 for c in parsed['cuts'])
    assert parsed['lufs'] == pytest.approx(-14.3, abs=0.5)
    assert parsed['true_peak'] == pytest.approx(-5.8, abs=0.5)


def test_parse_qa_empty_log():
    assert verify.parse_qa('') == {'black': [], 'freeze': [], 'silence': [], 'cuts': [],
                                   'lufs': None, 'true_peak': None}


@pytest.mark.parametrize('line, kind', [
    ('[Parsed_freezedetect_1 @ 0x1] lavfi.freezedetect.freeze_start: 1\n', 'freeze'),
    ('[Parsed_silencedetect_0 @ 0x1] silence_start: 1\n', 'silence'),
    ('[Parsed_blackdetect_0 @ 0x1] black_start:1\n', 'black'),
])
def test_unclosed_span_ends_at_output_end(line, kind):
    assert verify.parse_qa(line)[kind] == []
    parsed = verify.parse_qa(line, end=5.0)
    assert parsed[kind] == [(1.0, 5.0)]
    manifest = {'clips': [{'index': 0, 'file': 'a.MP4', 'lut': False, 'start': 2.0, 'duration': 5.0,
                           'label': 'x'}]}
    assert verify.qa_warnings(parsed, manifest, QA) == [f'WARN: {kind} 0:01.0–0:05.0 (#1 a.MP4 @ 3.0s)']


def test_report_closes_trailing_span_at_manifest_total(copy_project, monkeypatch):
    _qa_project(monkeypatch, '[Parsed_silencedetect_0 @ 0x1] silence_start: 2.5\n')
    tmp = Path(json.loads((copy_project / 'config.json').read_text())['tmp'])
    manifest = json.loads((tmp / 'render-manifest.final.json').read_text())
    total = verify.manifest_total(manifest)
    lines, ok = verify.report(copy_project)
    assert ok and lines[-1].startswith(f'WARN: silence 0:02.5–{verify.format_clock(total, True)} ')


def _manifest(*entries):
    return {'clips': [{'index': i, 'file': f, 'lut': False, 'start': s, 'duration': d, 'label': 'x'}
                      for i, f, s, d in entries]}


def _measured(manifest, *lengths):
    for clip, length in zip(manifest['clips'], lengths):
        clip['out_duration'] = length
    return manifest


def _parsed(**kw):
    return {'black': [], 'freeze': [], 'silence': [], 'cuts': [], 'lufs': None, 'true_peak': None, **kw}


def test_qa_warnings_map_to_clips():
    manifest = _manifest((0, 'a.MP4', 0.0, 200.0), (18, '22.08/DJI_0031_D.MP4', 13.0, 100.0))
    parsed = _parsed(black=[(221.2, 222.0)], freeze=[(205.0, 209.0)], silence=[(10.0, 14.5)],
                     cuts=[200.02, 250.0, 250.1], lufs=-33.1, true_peak=-0.2)
    warnings = verify.qa_warnings(parsed, manifest, QA)
    assert warnings == [
        'WARN: black 3:41.2–3:42.0 (#19 22.08/DJI_0031_D.MP4 @ 34.2s)',
        'WARN: freeze 3:25.0–3:29.0 (#19 22.08/DJI_0031_D.MP4 @ 18.0s)',
        'WARN: silence 0:10.0–0:14.5 (#1 a.MP4 @ 10.0s)',
        'WARN: flash 4:10.0 shot 0.10s (#19 22.08/DJI_0031_D.MP4 @ 63.0s)',
        'WARN: loudness -33.1 LUFS outside -30…-9',
        'WARN: true peak -0.2 dBTP above -1.0',
    ]


def test_qa_warnings_quiet_when_within_limits():
    manifest = _manifest((0, 'a.MP4', 0.0, 20.0), (1, 'b.MP4', 0.0, 20.0))
    parsed = _parsed(cuts=[20.03, 20.12, 25.0], lufs=-20.0, true_peak=-3.0)
    assert verify.qa_warnings(parsed, manifest, QA) == []


def test_qa_warnings_flash_between_join_and_cut():
    manifest = _manifest((0, 'a.MP4', 0.0, 10.0), (1, 'b.MP4', 0.0, 10.0))
    warnings = verify.qa_warnings(_parsed(cuts=[10.2]), manifest, QA)
    assert warnings == ['WARN: flash 0:10.0 shot 0.20s (#2 b.MP4 @ 0.0s)']


def test_qa_warnings_joins_follow_measured_clip_lengths():
    manifest = _measured(_manifest((0, 'a.MP4', 0.0, 10.0), (1, 'b.MP4', 0.0, 10.0)), 10.2, 10.2)
    assert verify.qa_warnings(_parsed(cuts=[10.2]), manifest, QA) == []


def test_locate_uses_measured_clip_lengths():
    manifest = _measured(_manifest((0, 'a.MP4', 5.0, 10.0), (1, 'b.MP4', 0.0, 10.0)), 10.3, 10.3)
    assert verify.locate(manifest, 10.1)['number'] == 1
    assert verify.locate(manifest, 10.4)['source_t'] == pytest.approx(0.1)
    assert verify.locate(manifest, 20.5)['number'] == 2


def _qa_project(monkeypatch, log):
    calls = []
    monkeypatch.setattr(verify, 'qa_scan', lambda path, cfg: calls.append(path) or log)
    return calls


FAKE_LOG = ('[Parsed_blackdetect_0 @ 0x1] black_start:1 black_end:2 black_duration:1\n'
            '[Parsed_ebur128_1 @ 0x1] Summary:\n\n  Integrated loudness:\n    I:         -40.0 LUFS\n'
            '  True peak:\n    Peak:       -0.1 dBFS\n')


def test_qa_warnings_do_not_fail_report(copy_project, monkeypatch):
    calls = _qa_project(monkeypatch, FAKE_LOG)
    lines, ok = verify.report(copy_project)
    assert ok and len(calls) == 1
    assert 'OK' in lines
    after_ok = lines[lines.index('OK') + 1:]
    assert after_ok[0].startswith('WARN: black 0:01.0–0:02.0 (#1 ')
    assert any(line.startswith('WARN: loudness -40.0 LUFS') for line in after_ok)
    assert any(line.startswith('WARN: true peak -0.1') for line in after_ok)


def test_warnings_follow_problem_lines(copy_project, monkeypatch):
    _qa_project(monkeypatch, FAKE_LOG)
    _edit(copy_project / 'clips.json', lambda c: c[1].update(lut=True))
    lines, ok = verify.report(copy_project)
    assert not ok
    first_warn = next(i for i, line in enumerate(lines) if line.startswith('WARN:'))
    assert lines[first_warn - 1].startswith('PROBLEM:')


def test_no_qa_flag_skips_scan(copy_project, monkeypatch):
    calls = _qa_project(monkeypatch, FAKE_LOG)
    lines, ok = verify.report(copy_project, qa=False)
    assert ok and calls == [] and lines[-1] == 'OK'
    proc = _cli(copy_project, '--no-qa')
    assert proc.returncode == 0 and 'WARN' not in proc.stdout


def test_qa_skipped_when_output_or_manifest_missing(copy_project, monkeypatch):
    calls = _qa_project(monkeypatch, FAKE_LOG)
    manifest = Path(json.loads((copy_project / 'config.json').read_text())['tmp']) / 'render-manifest.final.json'
    manifest.unlink()
    lines, ok = verify.report(copy_project)
    assert not ok and calls == [] and not any(line.startswith('WARN') for line in lines)
    (copy_project / 'SUMMARY_VIDEO.mp4').unlink()
    lines, ok = verify.report(copy_project)
    assert not ok and calls == []


def test_cli_scans_real_output(rendered_project):
    proc = _cli(rendered_project['project'])
    assert proc.returncode == 0, proc.stdout
    assert 'OK' in proc.stdout.splitlines()


def test_qa_flash_after_join_reported_with_measured_joins():
    manifest = _measured(_manifest((0, 'a.MP4', 0.0, 10.0), (1, 'b.MP4', 0.0, 10.0)), 10.0, 10.0)
    warnings = verify.qa_warnings(_parsed(cuts=[10.1]), manifest, QA)
    assert warnings == ['WARN: flash 0:10.0 shot 0.10s (#2 b.MP4 @ 0.0s)']


def test_qa_flash_after_join_masked_without_measured_joins():
    manifest = _manifest((0, 'a.MP4', 0.0, 10.0), (1, 'b.MP4', 0.0, 10.0))
    assert verify.qa_warnings(_parsed(cuts=[10.1]), manifest, QA) == []


def test_qa_partial_measurement_keeps_wide_tolerance():
    manifest = _manifest((0, 'a.MP4', 0.0, 10.0), (1, 'b.MP4', 0.0, 10.0), (2, 'c.MP4', 0.0, 10.0))
    manifest['clips'][0]['out_duration'] = 10.0
    assert verify.qa_warnings(_parsed(cuts=[10.1]), manifest, QA) == []


def test_parse_locate_not_required_last():
    args = verify.parse_args(['proj', '--locate', '12', '--draft'])
    assert args.draft is True and args.locate == ['12']


def test_parse_locate_negative_times():
    args = verify.parse_args(['proj', '--locate', '-5', '1:02'])
    assert args.locate == ['-5', '1:02']
    assert verify.parse_args(['proj', '--locate', '-1:00', '3']).locate == ['-1:00', '3']


def test_parse_locate_needs_a_time(capsys):
    with pytest.raises(SystemExit) as exc:
        verify.parse_args(['proj', '--locate'])
    assert exc.value.code == 2
    assert 'expected at least one argument' in capsys.readouterr().err
