import json
import shutil
import sys
from pathlib import Path

import pytest

import speech
from common import read_json, write_output
from conftest import write_stub_transcripts
from sample import (MissingTranscripts, add_speech, baseline_times, extract_thumb, loud_times,
                    merge_times, rescan, sample_project, scene_times, speech_times)


def test_scene_times_detects_cut(cut_clip):
    times = scene_times(cut_clip, 10.0)
    assert len(times) == 1
    assert times[0] == pytest.approx(1.5, abs=0.1)


def test_loud_times_detects_burst(loud_clip):
    times = loud_times(loud_clip, 3, 8.0)
    assert len(times) == 1
    assert times[0] == pytest.approx(2.15, abs=0.4)


def test_loud_times_silent_empty(silent_clip):
    assert loud_times(silent_clip, 3, 8.0) == []


def test_baseline_times():
    assert baseline_times(35, 10) == [5, 15, 25]
    assert baseline_times(2.8, 10) == [1.4]


def test_merge_prefers_scene():
    assert merge_times([(1.0, 'baseline'), (1.4, 'scene')], 10, 1.5) == [(1.4, 'scene')]


def test_merge_clamps_and_sorts():
    out = merge_times([(9.99, 'baseline'), (-1.0, 'loud'), (4.0, 'scene')], 10, 1.5)
    assert out == [(0.0, 'loud'), (4.0, 'scene'), (9.95, 'baseline')]


def test_candidates_short_clip(tmp_path, short_clip):
    root = tmp_path / 'p'
    root.mkdir()
    shutil.copy(short_clip, root / 'short.MP4')
    write_stub_transcripts(root)
    data = sample_project(root)
    assert len(data['candidates']) >= 1
    assert all(c['t'] < 0.8 for c in data['candidates'])


def test_thumbs_in_cache_not_project(project):
    write_stub_transcripts(project)
    data = sample_project(project)
    assert data['candidates']
    for c in data['candidates']:
        thumb = Path(c['thumb'])
        assert thumb.exists()
        assert project.resolve() not in thumb.resolve().parents
    assert [c['id'] for c in data['candidates']] == [f'c{i:04d}' for i in range(1, len(data['candidates']) + 1)]
    assert (project / 'moments.json').exists()
    assert data['scores'] == {} and data['groups'] == [] and data['must_find'] == []


def test_sample_refuses_existing(project):
    write_stub_transcripts(project)
    sample_project(project)
    with pytest.raises(FileExistsError):
        sample_project(project)
    sample_project(project, overwrite=True)


def test_rescan_appends_ids(project):
    write_stub_transcripts(project)
    data = sample_project(project)
    before = data['candidates']
    scores = {before[0]['id']: {'desc': 'kept'}}
    stored = read_json(project / 'moments.json')
    stored['scores'] = scores
    write_output(project, 'moments.json', stored, overwrite=True)
    new = rescan(project, ['22.08/square.MP4'], 0.5)
    after = read_json(project / 'moments.json')
    ids = [c['id'] for c in after['candidates']]
    assert new and len(ids) == len(set(ids))
    assert ids[:len(before)] == [c['id'] for c in before]
    assert min(c['id'] for c in new) > max(c['id'] for c in before)
    assert after['scores'] == scores
    assert all(Path(c['thumb']).exists() for c in new)


def test_extract_thumb(cut_clip, tmp_path):
    out = extract_thumb(cut_clip, 1.0, tmp_path / 'x' / 't.jpg', 160)
    assert out.exists() and out.stat().st_size > 0


def test_extract_thumb_rejects_stale_file(cut_clip, tmp_path):
    out = tmp_path / 't.jpg'
    out.write_bytes(b'stale')
    with pytest.raises(RuntimeError):
        extract_thumb(cut_clip, 100.0, out, 160)
    assert not out.exists()


def _fail_once(monkeypatch, fail_at_call=1):
    import sample
    real = sample.extract_thumb
    calls = {'n': 0}

    def flaky(path, t, out, width):
        calls['n'] += 1
        if calls['n'] == fail_at_call:
            raise RuntimeError(f'thumbnail failed at {t:.3f}s in {path}: boom')
        return real(path, t, out, width)

    monkeypatch.setattr(sample, 'extract_thumb', flaky)


def test_sample_skips_failed_thumbnail(project, monkeypatch, capsys):
    write_stub_transcripts(project)
    baseline = len(sample_project(project)['candidates'])
    _fail_once(monkeypatch)
    skipped = []
    data = sample_project(project, overwrite=True, skipped=skipped)
    assert len(data['candidates']) == baseline - 1
    assert [c['id'] for c in data['candidates']] == [f'c{i:04d}' for i in range(1, baseline)]
    assert len(skipped) == 1 and '22.08/square.MP4 @ ' in skipped[0] and 'boom' in skipped[0]
    assert 'warning: skipped' in capsys.readouterr().err


def test_rescan_skips_failed_thumbnail(project, monkeypatch):
    write_stub_transcripts(project)
    sample_project(project)
    _fail_once(monkeypatch)
    skipped = []
    new = rescan(project, ['22.08/square.MP4'], 0.5, skipped=skipped)
    assert new and len(skipped) == 1


def test_cli_lists_skipped(project, monkeypatch, capsys):
    write_stub_transcripts(project)
    import sample
    _fail_once(monkeypatch)
    monkeypatch.setattr(sys, 'argv', ['sample.py', str(project)])
    sample.main()
    out = capsys.readouterr().out
    assert 'skipped 1 timestamp' in out and '22.08/square.MP4 @ ' in out


def test_sample_overwrite_clears_cached_scores(project):
    write_stub_transcripts(project)
    from common import cache_dir
    sample_project(project)
    scores = cache_dir(project) / 'scores'
    scores.mkdir(parents=True, exist_ok=True)
    (scores / 'batch-c0001.json').write_text('{}')
    sample_project(project, overwrite=True)
    assert not scores.exists() or not any(scores.iterdir())


def _brief(root, force_exclude):
    write_output(root, 'brief.json', {'type': 'trip', 'source': str(root), 'description': '',
                                      'timeline': '', 'tone': '', 'must_find': [],
                                      'keep_memories': [], 'target_min': [5, 10], 'quality': 60,
                                      'music': None, 'force_include': [],
                                      'force_exclude': force_exclude})


def test_sample_skips_force_excluded_files(project, capsys):
    write_stub_transcripts(project)
    _brief(project, ['wide.MP4', '25.08', 'selfie stick'])
    data = sample_project(project)
    files = {c['file'] for c in data['candidates']}
    assert files == {'22.08/square.MP4'}


def test_cli_lists_force_excluded(project, monkeypatch, capsys):
    write_stub_transcripts(project)
    import sample
    _brief(project, ['22.08/wide.MP4'])
    monkeypatch.setattr(sys, 'argv', ['sample.py', str(project)])
    sample.main()
    out = capsys.readouterr().out
    assert 'not sampled (force_exclude): 22.08/wide.MP4' in out


def test_speech_times_collapses_close_starts():
    segs = [{'start': s, 'end': s + 0.5, 'text': 'x'} for s in (1.0, 1.8, 5.0)]
    assert speech_times(segs, 60, 1.5, 4) == [1.0, 5.0]


def test_speech_times_capped_per_minute():
    segs = [{'start': 2.0 * i, 'end': 2.0 * i + (1 if i % 7 else 1.5), 'text': 'x'} for i in range(600)]
    times = speech_times(segs, 1200, 1.5, 4)
    assert len(times) == 80
    assert times == sorted(times)
    assert all(int(t / 2) % 7 == 0 for t in times)


def test_sample_refuses_without_transcripts(project):
    with pytest.raises(MissingTranscripts) as exc:
        sample_project(project)
    assert len(exc.value.files) == 3
    assert not (project / 'moments.json').exists()


def test_sample_adds_speech_candidates(project, fake_whisper):
    speech.transcribe_project(project, progress=lambda _: None)
    data = sample_project(project)
    found = {c['file'] for c in data['candidates'] if c['source'] == 'speech' and abs(c['t'] - 0.5) < 0.01}
    assert found == {'22.08/square.MP4', '22.08/wide.MP4', '25.08/vertical.MP4'}


def _early_speech_project(tmp_path, loud_clip, monkeypatch):
    root = tmp_path / 'p'
    root.mkdir()
    shutil.copy(loud_clip, root / 'loud.MP4')
    payload = tmp_path / 'payload.json'
    payload.write_text(json.dumps({'transcription': [
        {'offsets': {'from': 100, 'to': 900}, 'text': ' early words'}]}))
    monkeypatch.setenv('FAKE_WHISPER_PAYLOAD', str(payload))
    return root


def test_add_speech_keeps_scores(tmp_path, loud_clip, fake_whisper, monkeypatch):
    root = _early_speech_project(tmp_path, loud_clip, monkeypatch)
    write_stub_transcripts(root)
    before = sample_project(root)['candidates']
    stored = read_json(root / 'moments.json')
    stored['scores'] = {'c0001': {'desc': 'kept'}}
    write_output(root, 'moments.json', stored, overwrite=True)
    speech.transcribe_project(root, overwrite=True, progress=lambda _: None)
    new, _ = add_speech(root)
    after = read_json(root / 'moments.json')
    assert [(c['file'], c['t']) for c in new] == [('loud.MP4', 0.1)]
    assert all(c['source'] == 'speech' for c in new)
    assert [c['id'] for c in after['candidates'][:len(before)]] == [c['id'] for c in before]
    assert min(c['id'] for c in new) > max(c['id'] for c in before)
    assert after['scores'] == {'c0001': {'desc': 'kept'}}
    assert all(Path(c['thumb']).exists() for c in new)


def test_rescan_refuses_without_transcripts(project):
    write_stub_transcripts(project)
    sample_project(project)
    speech.transcript_path(project, '22.08/square.MP4').unlink()
    with pytest.raises(MissingTranscripts):
        rescan(project, ['22.08/square.MP4'], 0.5)
    assert rescan(project, ['22.08/wide.MP4'], 0.5)


def test_cli_missing_transcripts_exit_2(project, monkeypatch, capsys):
    import sample
    monkeypatch.setattr(sys, 'argv', ['sample.py', str(project)])
    with pytest.raises(SystemExit) as exc:
        sample.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert 'ERROR: no transcript for 3 clips (first: ' in err and 'speech.py transcribe' in err


def test_cli_add_speech(tmp_path, loud_clip, fake_whisper, monkeypatch, capsys):
    import sample
    root = _early_speech_project(tmp_path, loud_clip, monkeypatch)
    write_stub_transcripts(root)
    sample_project(root)
    speech.transcribe_project(root, overwrite=True, progress=lambda _: None)
    monkeypatch.setattr(sys, 'argv', ['sample.py', str(root), '--add-speech'])
    sample.main()
    assert 'added 1 speech candidates, 0 scored candidates re-queued for scoring with speech' in capsys.readouterr().out


def _scored_old_project(tmp_path, loud_clip, monkeypatch, cand_t=0.5):
    root = _early_speech_project(tmp_path, loud_clip, monkeypatch)
    write_stub_transcripts(root)
    data = sample_project(root)
    keep = next(c for c in data['candidates'] if abs(c['t'] - cand_t) < 0.01) if any(
        abs(c['t'] - cand_t) < 0.01 for c in data['candidates']) else data['candidates'][0]
    keep['t'] = cand_t
    for c in data['candidates']:
        c.pop('speech_seen', None)
    data['scores'] = {c['id']: {'desc': 'old'} for c in data['candidates']}
    write_output(root, 'moments.json', data, overwrite=True)
    speech.transcribe_project(root, overwrite=True, progress=lambda _: None)
    return root, keep['id']


def test_add_speech_requeues_scored_candidate_near_speech(tmp_path, loud_clip, fake_whisper, monkeypatch):
    root, cid = _scored_old_project(tmp_path, loud_clip, monkeypatch)
    new, requeued = add_speech(root)
    after = read_json(root / 'moments.json')
    assert cid in requeued
    assert cid not in after['scores']
    assert all(c.get('speech_seen') for c in after['candidates'])


def test_add_speech_twice_requeues_nothing(tmp_path, loud_clip, fake_whisper, monkeypatch):
    root, cid = _scored_old_project(tmp_path, loud_clip, monkeypatch)
    add_speech(root)
    stored = read_json(root / 'moments.json')
    stored['scores'][cid] = {'desc': 'rescored'}
    write_output(root, 'moments.json', stored, overwrite=True)
    new, requeued = add_speech(root)
    assert requeued == []
    assert read_json(root / 'moments.json')['scores'][cid] == {'desc': 'rescored'}


def test_add_speech_never_requeues_speech_seen(tmp_path, loud_clip, fake_whisper, monkeypatch):
    root, cid = _scored_old_project(tmp_path, loud_clip, monkeypatch)
    stored = read_json(root / 'moments.json')
    for c in stored['candidates']:
        c['speech_seen'] = True
    write_output(root, 'moments.json', stored, overwrite=True)
    new, requeued = add_speech(root)
    assert requeued == []
    assert len(read_json(root / 'moments.json')['scores']) == len(stored['scores'])


def test_add_speech_requeues_without_speech_start_nearby(tmp_path, loud_clip, fake_whisper, monkeypatch):
    root, cid = _scored_old_project(tmp_path, loud_clip, monkeypatch)
    stored = read_json(root / 'moments.json')
    for c in stored['candidates']:
        if c['id'] == cid:
            c['t'] = 2.5
    write_output(root, 'moments.json', stored, overwrite=True)
    new, requeued = add_speech(root)
    assert cid in requeued
    assert cid not in read_json(root / 'moments.json')['scores']


def test_add_speech_requeues_nothing_when_already_sampled_with_speech(tmp_path, loud_clip, fake_whisper, monkeypatch):
    root, cid = _scored_old_project(tmp_path, loud_clip, monkeypatch)
    stored = read_json(root / 'moments.json')
    stored['candidates'].append({'id': 'c0099', 'file': 'loud.MP4', 't': 3.9, 'source': 'speech',
                                 'thumb': stored['candidates'][0]['thumb']})
    write_output(root, 'moments.json', stored, overwrite=True)
    new, requeued = add_speech(root)
    after = read_json(root / 'moments.json')
    assert requeued == []
    assert cid in after['scores']
    assert all(c.get('speech_seen') for c in after['candidates'])


def test_add_speech_skips_candidate_without_words(tmp_path, loud_clip, fake_whisper, monkeypatch):
    root, cid = _scored_old_project(tmp_path, loud_clip, monkeypatch)
    monkeypatch.setattr(speech, 'said_at', lambda *a, **k: None)
    new, requeued = add_speech(root)
    assert requeued == []
    assert cid in read_json(root / 'moments.json')['scores']


def test_add_speech_does_not_add_scores_key(tmp_path, loud_clip, fake_whisper, monkeypatch):
    root, cid = _scored_old_project(tmp_path, loud_clip, monkeypatch)
    stored = read_json(root / 'moments.json')
    del stored['scores']
    write_output(root, 'moments.json', stored, overwrite=True)
    add_speech(root)
    assert 'scores' not in read_json(root / 'moments.json')


def test_add_speech_dedupes_clamped_new_candidates(tmp_path, loud_clip, fake_whisper, monkeypatch):
    import sample
    root = tmp_path / 'p'
    root.mkdir()
    shutil.copy(loud_clip, root / 'loud.MP4')
    write_stub_transcripts(root)
    sample_project(root)
    stored = read_json(root / 'moments.json')
    stored['candidates'] = []
    write_output(root, 'moments.json', stored, overwrite=True)
    dur = next(c['duration'] for c in sample._load_probe(root)['clips'])
    monkeypatch.setattr(sample, 'speech_times', lambda *a, **k: [dur + 0.5, dur + 2.5])
    new, _ = add_speech(root)
    ts = [c['t'] for c in new]
    assert len(ts) == len(set(ts)) == 1


def test_sample_marks_speech_seen(project, fake_whisper):
    speech.transcribe_project(project, progress=lambda _: None)
    data = sample_project(project)
    assert data['candidates'] and all(c['speech_seen'] for c in data['candidates'])
