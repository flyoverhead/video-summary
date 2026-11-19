import json
import re
import os
import subprocess
import sys
from pathlib import Path

import pytest

from common import read_json, write_output
from moments import (default_top, group_project, group_routine, merge_project, must_find_table, pending_ids,
                     pick_project, rank, shortlist_md)


def score(**kw):
    base = {'people': 0, 'emotion': 0, 'view': 0, 'detail': 0, 'brief_match': 0, 'quality': 'good',
            'kind': 'highlight', 'process': None, 'desc': 'd', 'in': 0.0, 'out': 10.0, 'must_find': []}
    base.update(kw)
    return base


def cand(cid, file, t):
    return {'id': cid, 'file': file, 't': t, 'source': 'scene', 'thumb': f'/cache/{cid}.jpg'}


PROBE = {'clips': [
    {'file': 'a/1.MP4', 'duration': 60, 'created': '2026-08-22T10:00:00'},
    {'file': 'a/2.MP4', 'duration': 60, 'created': '2026-08-22T10:03:00'},
    {'file': 'a/3.MP4', 'duration': 60, 'created': '2026-08-22T12:30:00'},
]}


def routine(process, rank_boost=0, **kw):
    return score(kind='routine', process=process, view=rank_boost, **kw)


def test_rank_brief_match_weighs_double():
    assert rank(score(brief_match=3)) == 6
    assert rank(score(people=1, emotion=2, view=3, detail=4, brief_match=1)) == 12


def test_rank_poor_penalised():
    assert rank(score(brief_match=2, quality='poor')) == 1


def test_group_same_process_consecutive():
    moments = {
        'candidates': [cand('c1', 'a/1.MP4', 5), cand('c2', 'a/1.MP4', 30), cand('c3', 'a/2.MP4', 5),
                       cand('c4', 'a/2.MP4', 40)],
        'scores': {
            'c1': routine('metro ride'),
            'c2': routine('metro ride', 4),
            'c3': routine('metro ride', 1, **{'in': 2.0, 'out': 5.0}),
            'c4': routine('walking'),
        },
    }
    groups = group_routine(moments, PROBE, [4, 8])
    assert len(groups) == 2
    metro = next(g for g in groups if g['process'] == 'metro ride')
    assert metro['members'] == ['c1', 'c2', 'c3']
    assert metro['pick'] == 'c2'
    assert metro['clip_s'] == 8
    assert next(g for g in groups if g['process'] == 'walking')['members'] == ['c4']


def test_group_clip_s_capped_at_pick_length():
    moments = {'candidates': [cand('c1', 'a/1.MP4', 5)],
               'scores': {'c1': routine('walking', **{'in': 1.0, 'out': 4.5})}}
    assert group_routine(moments, PROBE, [4, 8])[0]['clip_s'] == 3.5


def test_group_splits_on_gap():
    moments = {
        'candidates': [cand('c1', 'a/1.MP4', 5), cand('c2', 'a/3.MP4', 5)],
        'scores': {'c1': routine('metro ride'), 'c2': routine('metro ride')},
    }
    groups = group_routine(moments, PROBE, [4, 8])
    assert [g['members'] for g in groups] == [['c1'], ['c2']]


def test_must_find_not_found_listed():
    brief = {'must_find': [{'id': 'm1', 'text': 'the bridge'}, {'id': 'm2', 'text': 'the cat'}]}
    moments = {'scores': {'c1': score(must_find=['m1']), 'c2': score(must_find=['m1'])}}
    moments['candidates'] = [cand('c1', 'a/1.MP4', 5), cand('c2', 'a/1.MP4', 30)]
    table = must_find_table(brief, moments)
    assert {k: table[0][k] for k in ('id', 'text', 'status', 'where')} == {
        'id': 'm1', 'text': 'the bridge', 'status': 'found', 'where': ['c1', 'c2']}
    assert table[1] == {'id': 'm2', 'text': 'the cat', 'status': 'not_found', 'where': [], 'best': None,
                        'required': [], 'extras': []}


def _full():
    brief = {'type': 'trip', 'must_find': [{'id': 'm2', 'text': 'the cat'}]}
    moments = {
        'candidates': [cand('c1', 'a/1.MP4', 5), cand('c2', 'a/1.MP4', 30), cand('c3', 'a/2.MP4', 5)],
        'scores': {
            'c1': routine('metro ride'),
            'c2': score(brief_match=4, desc='sunset', **{'in': 28.0, 'out': 34.0}),
            'c3': score(people=3, desc='friends'),
        },
        'lut': {'a/1.MP4': True},
    }
    moments['groups'] = group_routine(moments, PROBE, [4, 8])
    moments['must_find'] = must_find_table(brief, moments)
    return brief, moments


def test_shortlist_contains_groups_and_must_find():
    brief, moments = _full()
    md = shortlist_md(brief, PROBE, moments)
    assert '→ 1 ×' in md
    assert 'not found' in md
    assert '1 clips · metro ride → 1 × 8s (a/1.MP4 @ 0s)' in md
    assert md.index('a/1.MP4') < md.index('a/2.MP4')
    assert '8.0' in md and '/cache/c2.jpg' in md
    assert '28.0–34.0' in md
    assert 'metro' not in md.split('## Routine')[0]


def test_shortlist_top_n_limits_highlights():
    brief, moments = _full()
    md = shortlist_md(brief, PROBE, moments, top_n=1)
    assert 'sunset' in md and 'friends' not in md


def test_group_project_preserves_other_keys(tmp_path):
    brief, moments = _full()
    moments['groups'] = []
    moments['must_find'] = []
    write_output(tmp_path, 'brief.json', brief)
    write_output(tmp_path, 'probe.json', PROBE)
    write_output(tmp_path, 'moments.json', moments)
    group_project(tmp_path)
    out = read_json(tmp_path / 'moments.json')
    assert out['lut'] == {'a/1.MP4': True}
    assert out['candidates'] == moments['candidates']
    assert out['scores'] == moments['scores']
    assert out['groups'][0]['pick'] == 'c1'
    assert out['must_find'][0]['status'] == 'not_found'


MOMENTS_SCRIPT = Path(__file__).resolve().parent.parent / 'video-summary' / 'scripts' / 'moments.py'


def _merge_project(tmp_path):
    brief = {'type': 'trip', 'must_find': [{'id': 'm1', 'text': 'the bridge'}]}
    moments = {'candidates': [cand('c1', 'a/1.MP4', 5), cand('c2', 'a/1.MP4', 30), cand('c3', 'a/2.MP4', 5)],
               'scores': {'c1': routine('metro ride')}, 'groups': [], 'must_find': [],
               'lut': {'a/1.MP4': True}}
    write_output(tmp_path, 'brief.json', brief)
    write_output(tmp_path, 'probe.json', PROBE)
    write_output(tmp_path, 'moments.json', moments)
    return moments


def moments_cli(*args, stdin=None, home=None):
    env = ({**os.environ, 'HOME': str(home),
            'VIDEO_SUMMARY_CACHE_DIR': str(home / '.cache' / 'video-summary')} if home else None)
    return subprocess.run([sys.executable, str(MOMENTS_SCRIPT), *map(str, args)], input=stdin,
                          capture_output=True, text=True, env=env)


def test_merge_adds_scores_and_keeps_keys(tmp_path):
    before = _merge_project(tmp_path)
    remaining = merge_project(tmp_path, {'c2': score(must_find=['m1']), 'c3': score()})
    out = read_json(tmp_path / 'moments.json')
    assert set(out['scores']) == {'c1', 'c2', 'c3'}
    assert out['scores']['c1'] == before['scores']['c1']
    assert out['lut'] == {'a/1.MP4': True} and out['candidates'] == before['candidates']
    assert remaining == 0


def test_merge_rejects_unknown_id_and_missing_fields(tmp_path):
    _merge_project(tmp_path)
    bad = score()
    del bad['desc'], bad['in']
    with pytest.raises(ValueError) as exc:
        merge_project(tmp_path, {'c9': score(), 'c2': bad})
    msg = str(exc.value)
    assert 'c9' in msg and 'unknown candidate' in msg
    assert 'c2' in msg and 'desc' in msg and 'in' in msg
    assert 'c2' not in read_json(tmp_path / 'moments.json')['scores']


@pytest.mark.parametrize('field, value', [('people', 7), ('quality', 'great'), ('kind', 'peak'),
                                          ('must_find', ['m9']), ('out', -1.0), ('process', 3)])
def test_merge_rejects_bad_values(tmp_path, field, value):
    _merge_project(tmp_path)
    with pytest.raises(ValueError) as exc:
        merge_project(tmp_path, {'c2': score(**{field: value})})
    assert field in str(exc.value)


def test_pending_lists_unscored_in_order():
    moments = {'candidates': [cand('c1', 'a', 1), cand('c2', 'a', 2), cand('c3', 'a', 3)],
               'scores': {'c2': score()}}
    assert pending_ids(moments) == ['c1', 'c3']


def test_cli_merge_stdin_and_pending(tmp_path):
    _merge_project(tmp_path)
    home = tmp_path / 'home'
    proc = moments_cli(tmp_path, 'pending', '--batch', '1', home=home)
    lines = proc.stdout.splitlines()
    assert proc.returncode == 0 and len(lines) == 2
    path, _, ids = lines[0].split('\t')
    assert ids == 'c2' and path.endswith('/scores/batch-c2.json')
    assert path.startswith(str(home / '.cache' / 'video-summary')) and Path(path).parent.is_dir()
    assert lines[1].split('\t')[2] == 'c3'
    proc = moments_cli(tmp_path, 'merge', '-', stdin=json.dumps({'c2': score()}))
    assert proc.returncode == 0 and '1 merged, 1 unscored' in proc.stdout
    proc = moments_cli(tmp_path, 'merge', '-', stdin=json.dumps({'c7': score()}))
    assert proc.returncode == 1 and 'c7' in proc.stderr


def _three_groups(tmp_path):
    _merge_project(tmp_path)
    merge_project(tmp_path, {'c2': routine('walking', **{'in': 28.0, 'out': 31.0}),
                             'c3': routine('metro ride', **{'in': 1.0, 'out': 4.0})})
    return group_project(tmp_path)


def test_group_assigns_stable_ids(tmp_path):
    groups = _three_groups(tmp_path)['groups']
    assert [(g['id'], g['process'], g['members']) for g in groups] == [
        ('g1', 'metro ride', ['c1']), ('g2', 'walking', ['c2']), ('g3', 'metro ride', ['c3'])]


def test_pick_two_drops_hit_named_groups(tmp_path):
    _three_groups(tmp_path)
    pick_project(tmp_path, 'g1', None)
    pick_project(tmp_path, 'g3', None)
    groups = read_json(tmp_path / 'moments.json')['groups']
    assert [(g['id'], g.get('dropped', False)) for g in groups] == [('g1', True), ('g2', False), ('g3', True)]


def test_pick_swap_and_errors(tmp_path):
    _merge_project(tmp_path)
    merge_project(tmp_path, {'c2': routine('metro ride', **{'in': 28.0, 'out': 31.0}), 'c3': score()})
    group_project(tmp_path)
    assert read_json(tmp_path / 'moments.json')['groups'][0]['pick'] == 'c1'
    pick_project(tmp_path, 'g1', 'c2')
    group = read_json(tmp_path / 'moments.json')['groups'][0]
    assert group['pick'] == 'c2' and group['clip_s'] == 3.0
    with pytest.raises(ValueError):
        pick_project(tmp_path, 'g1', 'c3')
    with pytest.raises(ValueError):
        pick_project(tmp_path, 'g5', 'c2')


def test_overrides_survive_regroup(tmp_path):
    _merge_project(tmp_path)
    merge_project(tmp_path, {'c2': routine('metro ride', **{'in': 28.0, 'out': 31.0}),
                             'c3': routine('walking')})
    group_project(tmp_path)
    pick_project(tmp_path, 'g1', 'c2')
    pick_project(tmp_path, 'g2', None)
    out = group_project(tmp_path)
    assert out['group_overrides'] == {'metro ride|c1': {'pick': 'c2'}, 'walking|c3': {'dropped': True}}
    assert out['groups'][0]['pick'] == 'c2' and out['groups'][0]['clip_s'] == 3.0
    assert out['groups'][1]['dropped'] is True


def test_unmatched_override_reported(tmp_path, capsys):
    _three_groups(tmp_path)
    moments = read_json(tmp_path / 'moments.json')
    moments['group_overrides'] = {'ferry|c9': {'dropped': True}}
    write_output(tmp_path, 'moments.json', moments, overwrite=True)
    out = group_project(tmp_path)
    assert 'ferry|c9' in capsys.readouterr().err
    assert not any(g.get('dropped') for g in out['groups'])
    assert 'ferry|c9' in out['group_overrides']


def test_shortlist_labels_groups_and_dropped():
    brief, moments = _full()
    moments['groups'][0]['id'] = 'g1'
    assert '- g1 · 1 clips · metro ride' in shortlist_md(brief, PROBE, moments)
    moments['groups'][0]['dropped'] = True
    assert '- g1 · DROPPED · 1 clips · metro ride' in shortlist_md(brief, PROBE, moments)


def test_shortlist_reports_hidden_highlights():
    brief, moments = _full()
    md = shortlist_md(brief, PROBE, moments, top_n=1)
    assert '1 more highlights below rank 8.0 not shown — rerun with --top 2' in md
    assert 'not shown' not in shortlist_md(brief, PROBE, moments, top_n=2)


def test_default_top():
    assert default_top({'type': 'trip', 'target_min': [10, 15]}) == 150
    assert default_top({'type': 'sport', 'target_min': [1, 2]}) == 40
    assert default_top({'type': 'everyday'}) == 80


def _big_project(root, n=2000, scored=True):
    files = [f'{day}/DJI_2026082{day[1]}10{i:02d}00_{i:04d}_D.MP4' for day in ('22.08', '25.08') for i in range(50)]
    probe = {'clips': [{'file': f, 'duration': 600.0, 'fps': 50.0, 'width': 3840, 'height': 3840,
                        'audio_channels': 2, 'created': f'2026-08-22T10:{i % 60:02d}:00'}
                       for i, f in enumerate(files)],
             'frame': {'shape': 'square', 'width': 2560, 'height': 2560, 'fps': 50.0}}
    thumbs = '/Users/someone/.cache/video-summary/long trip name-1a2b3c4d/thumbs'
    cands = [{'id': f'c{i:04d}', 'file': files[i % len(files)], 't': float(i % 590), 'source': 'baseline',
              'thumb': f'{thumbs}/c{i:04d}.jpg'} for i in range(1, n + 1)]
    scores = {}
    if scored:
        for i, c in enumerate(cands):
            kind = 'routine' if i % 3 else 'highlight'
            scores[c['id']] = score(kind=kind, process=f'walking through market number {i % 30}' if kind == 'routine' else None,
                                    people=i % 6, view=(i * 7) % 6, desc='A long one-line description of who, where and what happens here',
                                    must_find=['m1'] if i % 97 == 0 else [], **{'in': c['t'], 'out': c['t'] + 8})
    brief = {'type': 'trip', 'target_min': [10, 15], 'must_find': [{'id': 'm1', 'text': 'the bridge'}]}
    moments = {'candidates': cands, 'scores': scores, 'groups': [], 'must_find': [], 'lut': {f: True for f in files}}
    write_output(root, 'brief.json', brief)
    write_output(root, 'probe.json', probe)
    write_output(root, 'moments.json', moments)
    if scored:
        group_project(root)
    return moments


def test_pending_writes_compact_batch_inputs(tmp_path):
    from moments import pending_batches
    _big_project(tmp_path, scored=False)
    moments = read_json(tmp_path / 'moments.json')
    moments['scores'] = {'c0001': routine('metro ride'), 'c0002': routine('walking')}
    write_output(tmp_path, 'moments.json', moments, overwrite=True)
    batches = pending_batches(tmp_path, 40)
    assert len(batches) == 50
    scores_path, input_path, ids = batches[0]
    assert scores_path.name == 'batch-c0003.json' and input_path.name == 'input-c0003.json'
    assert input_path.parent == scores_path.parent
    data = read_json(input_path)
    assert [c['id'] for c in data['candidates']] == ids == [f'c{i:04d}' for i in range(3, 43)]
    first = data['candidates'][0]
    assert set(first) == {'id', 'file', 't', 'thumb', 'duration'} and first['duration'] == 600.0
    assert data['process_labels'] == ['metro ride', 'walking']
    assert all(p.stat().st_size < 12_000 for _, p, _ in batches)


def test_digest_small_for_2000_candidates(tmp_path):
    from moments import digest_project
    _big_project(tmp_path)
    path = digest_project(tmp_path)
    assert tmp_path.resolve() not in path.resolve().parents
    size = path.stat().st_size
    full = (tmp_path / 'moments.json').stat().st_size
    lines = path.read_text().splitlines()
    assert size < 2000 * 110 + 20_000 and size * 3 < full, (size, full)
    cand_lines = [line for line in lines if re.match(r'c\d{4} ', line)]
    assert len(cand_lines) == 2000 and max(len(line.encode()) for line in cand_lines) < 200


def test_digest_content(tmp_path):
    from moments import digest_text
    brief, moments = _full()
    moments['groups'][0]['id'] = 'g1'
    moments['scores']['c2']['must_find'] = ['m2']
    moments['must_find'] = must_find_table(brief, moments)
    text = digest_text(brief, PROBE, moments)
    assert 'routine_clip_s 4-8' in text and 'target_min 10-15' in text
    assert 'f1 a/1.MP4 60 2026-08-22T10:00:00 lut' in text
    assert 'f2 a/2.MP4 60 2026-08-22T10:03:00 -' in text
    assert re.search(r'^g1 pick c1 f1 in 0 clip_s 8 · 1 members · metro ride$', text, re.M)
    assert re.search(r'^m2 found \| required c2 f1 28-34 \| extras - \| the cat$', text, re.M)
    cands = [line for line in text.splitlines() if re.match(r'c\d', line)]
    assert cands[0].startswith('c2 f1 30 28-34 r8 H ') and cands[0].endswith('| sunset')
    assert any(line.startswith('c1 f1 5 0-10 r0 R ') and 'metro ride' in line for line in cands)


def test_cli_pending_and_digest_print_paths(tmp_path):
    _merge_project(tmp_path)
    home = tmp_path / 'home'
    proc = moments_cli(tmp_path, 'pending', '--batch', '1', home=home)
    scores, inputs, ids = proc.stdout.splitlines()[0].split('\t')
    assert ids == 'c2' and Path(inputs).is_file() and inputs.endswith('/scores/input-c2.json')
    merge_project(tmp_path, {'c2': score(), 'c3': score()})
    proc = moments_cli(tmp_path, 'digest', home=home)
    assert proc.returncode == 0
    path = Path(proc.stdout.strip())
    assert path.is_file() and path.name == 'digest.txt' and str(path).startswith(str(home))


def test_shortlist_lists_group_members():
    brief, moments = _full()
    moments['groups'][0]['id'] = 'g1'
    assert '1 × 8s (a/1.MP4 @ 0s) · members c1' in shortlist_md(brief, PROBE, moments)


def _mf_moments():
    brief = {'type': 'trip', 'must_find': [{'id': 'm1', 'text': 'the bridge'}]}
    moments = {'candidates': [cand('c1', 'a/1.MP4', 5), cand('c2', 'a/1.MP4', 30), cand('c3', 'a/2.MP4', 12),
                              cand('c4', 'a/2.MP4', 40)],
               'scores': {'c1': score(brief_match=3, must_find=['m1']),
                          'c2': score(brief_match=1, must_find=['m1'], **{'in': 28.0, 'out': 34.0}),
                          'c3': score(brief_match=2, must_find=['m1'], **{'in': 10.0, 'out': 16.0})},
               'groups': []}
    moments['must_find'] = must_find_table(brief, moments)
    return brief, moments


def test_must_find_best_required_extras():
    _, moments = _mf_moments()
    row = moments['must_find'][0]
    assert row['best'] == {'id': 'c1', 'file': 'a/1.MP4', 't': 5, 'thumb': '/cache/c1.jpg'}
    assert row['required'] == ['c1', 'c3']
    assert row['extras'] == ['c2']


def test_shortlist_must_find_best_match_is_checkable():
    brief, moments = _mf_moments()
    md = shortlist_md(brief, PROBE, moments)
    assert '| m1 | the bridge | found | a/1.MP4 @ 5s · /cache/c1.jpg | c1, c2, c3 |' in md


def test_shortlist_lists_unscored():
    brief, moments = _mf_moments()
    md = shortlist_md(brief, PROBE, moments)
    assert '## Unscored' in md
    assert '1 unscored candidates (not in the cut until scored):' in md
    assert '- c4 · a/2.MP4 @ 40s · /cache/c4.jpg' in md
    moments['scores']['c4'] = score()
    assert '## Unscored' not in shortlist_md(brief, PROBE, moments)


def test_uncovered_by_rank_with_must_find():
    from moments import uncovered
    _, moments = _mf_moments()
    moments['scores']['c4'] = score(people=5, desc='kids', **{'in': 38.0, 'out': 44.0})
    clips = [{'file': 'a/1.MP4', 'start': 0.0, 'duration': 10.0, 'label': 'x', 'lut': False}]
    rows = uncovered(moments, clips)
    assert [r['id'] for r in rows] == ['c4', 'c3', 'c2']
    assert rows[1] == {'id': 'c3', 'rank': 4.0, 'file': 'a/2.MP4', 'in': 10.0, 'out': 16.0, 'desc': 'd',
                       'thumb': '/cache/c3.jpg', 'must_find': ['m1']}


def test_uncovered_overlap_rule():
    from moments import uncovered
    _, moments = _mf_moments()
    moments['scores']['c4'] = score(kind='routine', process='walk')
    half = [{'file': 'a/1.MP4', 'start': 31.0, 'duration': 10.0, 'label': 'x', 'lut': False},
            {'file': 'a/2.MP4', 'start': 14.5, 'duration': 5.0, 'label': 'y', 'lut': False}]
    ids = [r['id'] for r in uncovered(moments, half)]
    assert 'c2' not in ids
    assert 'c3' in ids
    assert 'c4' not in ids


def test_cli_uncovered(tmp_path):
    brief, moments = _mf_moments()
    write_output(tmp_path, 'brief.json', brief)
    write_output(tmp_path, 'probe.json', PROBE)
    write_output(tmp_path, 'moments.json', moments)
    clips = [{'file': 'a/1.MP4', 'start': 0.0, 'duration': 10.0, 'label': 'x', 'lut': False}]
    proc = moments_cli(tmp_path, 'uncovered', '-', stdin=json.dumps(clips))
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert lines[0] == '2 of 3 scored highlights not covered by the clips'
    assert lines[1] == '- c3 · rank 4 · m1 · a/2.MP4 · 10–16 · d · /cache/c3.jpg'
    src = tmp_path / 'draft.json'
    src.write_text(json.dumps(clips))
    assert moments_cli(tmp_path, 'uncovered', src).stdout == proc.stdout
    assert moments_cli(tmp_path, 'uncovered', '-', stdin='{bad').returncode == 1


def test_pick_on_dropped_group_undrops(tmp_path):
    _merge_project(tmp_path)
    merge_project(tmp_path, {'c2': routine('metro ride', **{'in': 28.0, 'out': 31.0}), 'c3': score()})
    group_project(tmp_path)
    pick_project(tmp_path, 'g1', None)
    group = pick_project(tmp_path, 'g1', 'c2')
    assert 'dropped' not in group and group['pick'] == 'c2'
    out = group_project(tmp_path)
    assert 'dropped' not in out['groups'][0] and out['groups'][0]['pick'] == 'c2'
    assert out['group_overrides'] == {'metro ride|c1': {'pick': 'c2'}}


def test_pending_removes_stale_scores_file(tmp_path):
    from moments import pending_batches
    _merge_project(tmp_path)
    scores_path = pending_batches(tmp_path, 40)[0][0]
    scores_path.write_text('{"c2": "stale"}')
    again = pending_batches(tmp_path, 40)[0][0]
    assert again == scores_path and not scores_path.exists()


def _speech_project(root):
    import speech
    brief = {'type': 'trip', 'must_find': []}
    moments = {'candidates': [cand('c1', 'a/1.MP4', 1.0), cand('c2', 'a/1.MP4', 40.0)], 'scores': {}}
    write_output(root, 'brief.json', brief)
    write_output(root, 'probe.json', PROBE)
    write_output(root, 'moments.json', moments)
    segments = [{'start': 0.5, 'end': 1.5, 'text': 'look at this'}]
    speech._write_transcript(root, 'a/1.MP4', 'en', segments, [], None)


def test_batch_input_includes_said(tmp_path):
    from moments import batch_input, pending_batches
    _speech_project(tmp_path)
    _, input_path, _ = pending_batches(tmp_path, 40)[0]
    rows = {r['id']: r for r in read_json(input_path)['candidates']}
    assert rows['c1']['said'] == 'look at this'
    assert 'said' not in rows['c2']
    moments = read_json(tmp_path / 'moments.json')
    assert 'said' not in batch_input(moments, PROBE, ['c1'])['candidates'][0]
    assert batch_input(moments, PROBE, ['c1'], {'c1': 'hi'})['candidates'][0]['said'] == 'hi'


def test_digest_line_has_said_truncated():
    from moments import digest_text
    brief, moments = _full()
    said = 'x' * 100
    text = digest_text(brief, PROBE, moments, {'c2': said})
    line = next(line for line in text.splitlines() if line.startswith('c2 '))
    assert line.endswith(' | said: ' + 'x' * 60)
    plain = next(line for line in digest_text(brief, PROBE, moments).splitlines() if line.startswith('c2 '))
    assert 'said:' not in plain


def test_digest_project_builds_said(tmp_path):
    from moments import digest_project
    _speech_project(tmp_path)
    moments = read_json(tmp_path / 'moments.json')
    moments['scores'] = {'c1': score(desc='kid'), 'c2': score(desc='road')}
    write_output(tmp_path, 'moments.json', moments, overwrite=True)
    text = digest_project(tmp_path).read_text()
    assert re.search(r'^c1 .*\| kid \| said: look at this$', text, re.M)
    assert not re.search(r'^c2 .*said:', text, re.M)


def _snap(clips, segments, silences=(), file='a/1.MP4', duration=10.0, check_only=False):
    from moments import snap_clips
    transcripts = {file: {'segments': [{'start': a, 'end': b, 'text': 'x'} for a, b in segments],
                          'silences': [list(s) for s in silences]}}
    return snap_clips(clips, transcripts, {file: duration}, 1.5, 0.2, check_only)


def _clip(start, duration, file='a/1.MP4'):
    return {'file': file, 'start': start, 'duration': duration, 'label': 'x', 'lut': False}


def test_snap_extends_start_to_segment_start():
    rows, notes = _snap([_clip(30.0, 5.0)], [(28.8, 33.0)], duration=60)
    assert rows[0]['start'] == 28.6
    assert rows[0]['duration'] == 6.4
    assert '30.0 \u2192 28.6' in notes[0]
    assert notes[0].startswith('#1 start')


def test_snap_uses_silence_within_pad():
    rows, _ = _snap([_clip(30.0, 5.0)], [(28.8, 33.0)], [(28.7, 28.75)], duration=60)
    assert rows[0]['start'] == 28.7


def test_snap_leaves_edge_beyond_window_and_notes_it():
    rows, notes = _snap([_clip(31.0, 5.0)], [(28.8, 33.0)], duration=60)
    assert rows[0]['start'] == 31.0
    assert rows[0]['duration'] == 5.0
    assert 'no pause within 1.5 s' in notes[0]


def test_snap_end_extends_outward():
    rows, notes = _snap([_clip(36.0, 4.5)], [(38.0, 41.0)], duration=60)
    assert rows[0]['start'] == 36.0
    assert rows[0]['duration'] == 5.2
    assert '40.5 \u2192 41.2' in notes[0]


def test_snap_clamps_to_file_bounds():
    rows, _ = _snap([_clip(0.5, 3.0)], [(0.0, 1.0)])
    assert rows[0]['start'] == 0.0
    rows, _ = _snap([_clip(5.0, 4.8)], [(9.5, 10.2)])
    assert rows[0]['start'] + rows[0]['duration'] == 10.0


def test_snap_edge_on_segment_boundary_is_left():
    rows, notes = _snap([_clip(28.8, 4.2)], [(28.8, 33.0)], duration=60)
    assert rows[0] == _clip(28.8, 4.2)
    assert notes == []


def test_snap_check_changes_nothing():
    clips = [_clip(30.0, 5.0)]
    rows, notes = _snap(clips, [(28.8, 33.0)], duration=60, check_only=True)
    assert rows == clips
    assert notes == ['#1 start 30.0 inside speech']


def test_snap_no_transcript_passthrough():
    from moments import snap_clips
    clips = [_clip(30.0, 5.0)]
    rows, notes = snap_clips(clips, {}, {'a/1.MP4': 60}, 1.5, 0.2)
    assert rows == clips
    assert notes == []


def test_cli_snap(tmp_path, monkeypatch):
    import common
    import speech
    home = tmp_path / 'home'
    monkeypatch.setattr(common, 'CACHE_ROOT', home / '.cache' / 'video-summary')
    write_output(tmp_path, 'probe.json', PROBE)
    speech._write_transcript(tmp_path, 'a/1.MP4', 'en', [{'start': 28.8, 'end': 33.0, 'text': 'x'}], [], None)
    clips = [_clip(30.0, 5.0)]
    proc = moments_cli(tmp_path, 'snap', '-', stdin=json.dumps(clips), home=home)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)[0]['start'] == 28.6
    assert '#1 start 30.0 \u2192 28.6 (mid-speech)' in proc.stderr
    checked = moments_cli(tmp_path, 'snap', '-', '--check', stdin=json.dumps(clips), home=home)
    assert json.loads(checked.stdout) == clips
    assert '#1 start 30.0 inside speech' in checked.stderr
    assert moments_cli(tmp_path, 'snap', '-', stdin='{bad', home=home).returncode == 1


def _end(row):
    return round(row['start'] + row['duration'], 3)


def test_snap_same_file_neighbours_do_not_overlap():
    rows, notes = _snap([_clip(10.0, 5.0), _clip(17.5, 5.0)], [(14.0, 16.5), (16.6, 19.0)], duration=60)
    assert _end(rows[0]) == 16.6
    assert rows[1]['start'] == 16.6
    assert _end(rows[1]) == 22.5
    assert '#2 start 17.5 → 16.6 (clamped to #1 end)' in notes
    assert not any('16.5' in x for x in notes)


def test_snap_neighbours_snapping_into_one_utterance_touch():
    rows, notes = _snap([_clip(10.0, 5.0), _clip(15.1, 4.9)], [(14.0, 16.0)], duration=60)
    assert _end(rows[0]) == 15.1
    assert rows[1]['start'] == 15.1
    assert _end(rows[1]) == 20.0
    assert '#1 end 15.0 → 15.1 (clamped to #2 start)' in notes
    assert notes == ['#1 end 15.0 → 15.1 (clamped to #2 start)']


def test_snap_moved_end_clamped_to_unmoved_neighbour_start():
    rows, notes = _snap([_clip(10.0, 5.0), _clip(15.6, 3.0)], [(14.0, 15.5)], duration=60)
    assert _end(rows[0]) == 15.6
    assert rows[1] == _clip(15.6, 3.0)
    assert '#1 end 15.0 → 15.6 (clamped to #2 start)' in notes
    assert not any('15.7' in x for x in notes)


def test_snap_neighbours_in_other_files_untouched():
    clips = [_clip(10.0, 5.0), _clip(15.1, 4.9, file='b/2.MP4')]
    rows, _ = _snap(clips, [(14.0, 16.0)], duration=60)
    assert _end(rows[0]) == 16.2
    assert rows[1] == clips[1]


def test_snap_pad_stops_at_previous_segment_end():
    rows, notes = _snap([_clip(30.0, 5.0)], [(27.0, 28.7), (28.8, 33.0)], duration=60)
    assert rows[0]['start'] == 28.7
    assert '30.0 → 28.7' in notes[0]


def test_snap_pad_stops_at_next_segment_start():
    rows, _ = _snap([_clip(36.0, 4.5)], [(38.0, 41.0), (41.1, 43.0)], duration=60)
    assert _end(rows[0]) == 41.1


def test_snap_end_into_silence():
    rows, notes = _snap([_clip(36.0, 4.5)], [(38.0, 41.0)], [(41.05, 41.1)], duration=60)
    assert _end(rows[0]) == 41.1
    assert '40.5 → 41.1' in notes[0]


def test_snap_end_beyond_window_note_is_rounded():
    rows, notes = _snap([_clip(0.1, 0.2)], [(0.25, 5.0)], duration=60)
    assert rows[0] == _clip(0.1, 0.2)
    assert notes == ['#1 end 0.3 inside speech, no pause within 1.5 s']


def test_snap_check_reports_end_edge():
    clips = [_clip(36.0, 4.5)]
    rows, notes = _snap(clips, [(38.0, 41.0)], duration=60, check_only=True)
    assert rows == clips
    assert notes == ['#1 end 40.5 inside speech']


def _mute_clip(path, gap_at, gap_s=0.7, video=True):
    from common import run
    parts = [('sine=frequency=440:sample_rate=48000', gap_at), ('anullsrc=r=48000:cl=mono', gap_s),
             ('sine=frequency=440:sample_rate=48000', 2.0)]
    cmd = ['ffmpeg', '-v', 'error', '-y']
    for src, d in parts:
        cmd += ['-f', 'lavfi', '-t', str(d), '-i', src]
    cmd += ['-filter_complex', '[0][1][2]concat=n=3:v=0:a=1[a]']
    if video:
        cmd += ['-f', 'lavfi', '-t', '8', '-i', 'color=c=black:s=64x64:r=10']
    cmd += ['-map', '[a]', '-c:a', 'aac']
    if video:
        cmd += ['-map', '3:v', '-c:v', 'mpeg4']
    cmd.append(str(path))
    run(cmd)
    return path


def test_mic_mute_finds_gap(tmp_path):
    from moments import mic_mute
    _mute_clip(tmp_path / 'm.mp4', 3.0)
    gap = mic_mute(tmp_path, 'm.mp4')
    assert gap is not None
    assert abs(gap[0] - 3.0) < 0.05 and abs(gap[1] - 3.7) < 0.05


def test_mic_mute_ignores_late_gap(tmp_path):
    from moments import mic_mute
    _mute_clip(tmp_path / 'late.mp4', 4.0)
    assert mic_mute(tmp_path, 'late.mp4') is None


def test_mic_mute_video_only_file(tmp_path):
    from common import run
    from moments import mic_mute
    run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-t', '3', '-i', 'color=c=black:s=64x64:r=10',
         '-c:v', 'mpeg4', str(tmp_path / 'v.mp4')])
    assert mic_mute(tmp_path, 'v.mp4') is None


def _snap_mute(clips, check_only=False, mutes=None):
    from moments import snap_clips
    return snap_clips(clips, {}, {'a/1.MP4': 60}, 1.5, 0.2, check_only, mutes or {'a/1.MP4': (1.0, 1.7)})


def test_snap_skips_mic_mute_keeps_end():
    rows, notes = _snap_mute([_clip(0.0, 5.0)])
    assert rows[0]['start'] == 1.8
    assert _end(rows[0]) == 5.0
    assert notes == ['#1 start 0.0 → 1.8 (mic switch-on mute)']


def test_snap_mute_leaves_clip_after_gap():
    rows, notes = _snap_mute([_clip(2.0, 3.0)])
    assert rows[0] == _clip(2.0, 3.0)
    assert notes == []


def test_snap_mute_check_only_notes_and_keeps():
    clips = [_clip(0.0, 5.0)]
    rows, notes = _snap_mute(clips, check_only=True)
    assert rows == clips
    assert notes == ['#1 start 0.0 plays mic switch-on mute']


def test_snap_mute_clip_inside_gap_unchanged():
    rows, notes = _snap_mute([_clip(1.1, 0.5)])
    assert rows[0] == _clip(1.1, 0.5)
    assert notes == ['#1 inside mic switch-on mute, not moved']


def test_snap_mute_other_file_untouched():
    rows, notes = _snap_mute([_clip(0.0, 5.0, file='a/2.MP4')])
    assert rows[0] == _clip(0.0, 5.0, file='a/2.MP4')
    assert notes == []


def test_unoverlap_double_clamp_keeps_one_note_per_edge():
    from moments import _unoverlap
    clips = [_clip(10.0, 5.0), _clip(20.0, 5.0), _clip(16.0, 3.0)]
    edges = [[10.0, 16.7], [15.0, 25.0], [16.0, 19.0]]
    notes = []
    _unoverlap(clips, edges, notes)
    assert edges[1][0] == 19.0
    assert [x for x in notes if x.startswith('#2 start ') and '→' in x] == ['#2 start 20.0 → 19.0 (clamped to #3 end)']
