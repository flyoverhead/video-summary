import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import cache_dir, defaults, read_json, write_output  # noqa: E402


def rank(score: dict) -> float:
    total = (2 * score.get('brief_match', 0) + score.get('people', 0) + score.get('emotion', 0)
             + score.get('view', 0) + score.get('detail', 0))
    if score.get('quality') == 'poor':
        total -= 3
    return float(total)


def _fmt(value: float) -> str:
    return f'{value:g}'


def group_routine(moments: dict, probe: dict, routine_clip_s: list[float],
                  max_gap_s: float = 300) -> list[dict]:
    created = {c['file']: datetime.fromisoformat(c['created']).timestamp() for c in probe['clips']}
    cands = {c['id']: c for c in moments['candidates']}
    scores = moments['scores']
    items = []
    for cid, sc in scores.items():
        if sc.get('kind') != 'routine' or cid not in cands:
            continue
        cand = cands[cid]
        items.append((created.get(cand['file'], 0.0), cand['t'], cid))
    items.sort()
    groups: list[dict] = []
    prev_abs = None
    for clip_created, t, cid in items:
        absolute = clip_created + t
        process = scores[cid].get('process')
        current = groups[-1] if groups else None
        if (current is None or current['process'] != process
                or absolute - prev_abs > max_gap_s):
            current = {'process': process, 'members': []}
            groups.append(current)
        current['members'].append(cid)
        prev_abs = absolute
    for n, group in enumerate(groups, 1):
        group['id'] = f'g{n}'
        group['pick'] = max(group['members'], key=lambda m: rank(scores[m]))
        pick = scores[group['pick']]
        group['clip_s'] = min(float(routine_clip_s[1]), pick['out'] - pick['in'])
    return groups


def _best(ids: list[str], scores: dict) -> str:
    return max(ids, key=lambda cid: rank(scores[cid]))


def _required(where: list[str], scores: dict, cands: dict) -> list[str]:
    by_file: dict[str, list[str]] = {}
    for cid in where:
        by_file.setdefault(cands[cid]['file'], []).append(cid)
    picks = [_best(ids, scores) for ids in by_file.values()]
    return sorted(picks, key=lambda cid: -rank(scores[cid]))


def must_find_table(brief: dict, moments: dict) -> list[dict]:
    scores = moments.get('scores', {})
    cands = {c['id']: c for c in moments.get('candidates', [])}
    table = []
    for item in brief.get('must_find', []):
        where = [cid for cid, sc in scores.items() if item['id'] in sc.get('must_find', [])]
        located = [cid for cid in where if cid in cands]
        best = None
        required: list[str] = []
        if located:
            top = cands[_best(located, scores)]
            best = {k: top[k] for k in ('id', 'file', 't', 'thumb')}
            required = _required(located, scores, cands)
        table.append({'id': item['id'], 'text': item['text'],
                      'status': 'found' if where else 'not_found', 'where': where, 'best': best,
                      'required': required, 'extras': [cid for cid in where if cid not in required]})
    return table


def default_top(brief: dict) -> int:
    target = brief.get('target_min') or defaults()['types'][brief.get('type', 'trip')]['target_min']
    return max(40, math.ceil(target[1] * 60 / 6))


def shortlist_md(brief: dict, probe: dict, moments: dict, top_n: int | None = None) -> str:
    if top_n is None:
        top_n = default_top(brief)
    scores = moments['scores']
    cands = {c['id']: c for c in moments['candidates']}
    highlights = [cid for cid, sc in scores.items() if sc.get('kind') != 'routine' and cid in cands]
    highlights.sort(key=lambda cid: rank(scores[cid]), reverse=True)
    top = set(highlights[:top_n])
    lines = ['# Shortlist', '', '## Highlights', '']
    for clip in probe['clips']:
        ids = sorted((cid for cid in top if cands[cid]['file'] == clip['file']),
                     key=lambda cid: scores[cid]['in'])
        if not ids:
            continue
        lines += [f'### {clip["file"]}', '']
        for cid in ids:
            sc = scores[cid]
            lines.append(f'- {cid} · rank {rank(sc):.1f} · {clip["file"]} · '
                         f'{sc["in"]:.1f}–{sc["out"]:.1f} · {sc["desc"]} · {cands[cid]["thumb"]}')
        lines.append('')
    hidden = len(highlights) - len(top)
    if hidden > 0:
        lowest = rank(scores[highlights[top_n - 1]]) if top_n > 0 else rank(scores[highlights[0]])
        lines += [f'{hidden} more highlights below rank {lowest:.1f} not shown — '
                  f'rerun with --top {len(highlights)}', '']
    lines += ['## Routine', '']
    for n, group in enumerate(moments.get('groups', []), 1):
        pick = scores[group['pick']]
        file = cands[group['pick']]['file']
        flag = 'DROPPED · ' if group.get('dropped') else ''
        lines.append(f'- {group.get("id", f"g{n}")} · {flag}{len(group["members"])} clips · {group["process"]} → '
                     f'1 × {_fmt(group["clip_s"])}s ({file} @ {_fmt(pick["in"])}s) · '
                     f'members {" ".join(group["members"])}')
    lines += _unscored_md(moments)
    lines += ['', '## Must-find', '', '| id | text | status | best match | where |', '|---|---|---|---|---|']
    for row in moments.get('must_find', []):
        status = 'found' if row['status'] == 'found' else 'not found'
        best = row.get('best')
        match = f'{best["file"]} @ {_fmt(best["t"])}s · {best["thumb"]}' if best else '-'
        lines.append(f'| {row["id"]} | {row["text"]} | {status} | {match} | {", ".join(row["where"])} |')
    return '\n'.join(lines) + '\n'


def _unscored_md(moments: dict) -> list[str]:
    ids = pending_ids(moments)
    if not ids:
        return []
    cands = {c['id']: c for c in moments['candidates']}
    lines = ['', '## Unscored', '', f'{len(ids)} unscored candidates (not in the cut until scored):', '']
    return lines + [f'- {cid} · {cands[cid]["file"]} @ {_fmt(cands[cid]["t"])}s · {cands[cid]["thumb"]}'
                    for cid in ids]


def _covered(cand: dict, sc: dict, clips: list[dict]) -> bool:
    lo, hi = sc['in'], sc['out']
    for clip in clips:
        if clip.get('file') != cand['file']:
            continue
        start, end = float(clip['start']), float(clip['start']) + float(clip['duration'])
        if start <= cand['t'] <= end or min(hi, end) - max(lo, start) >= (hi - lo) / 2:
            return True
    return False


def uncovered(moments: dict, clips: list[dict]) -> list[dict]:
    scores = moments.get('scores', {})
    cands = {c['id']: c for c in moments['candidates']}
    ids = [cid for cid, sc in scores.items() if sc.get('kind') != 'routine' and cid in cands
           and not _covered(cands[cid], sc, clips)]
    ids.sort(key=lambda cid: -rank(scores[cid]))
    return [{'id': cid, 'rank': rank(scores[cid]), 'file': cands[cid]['file'], 'in': scores[cid]['in'],
             'out': scores[cid]['out'], 'desc': scores[cid].get('desc', ''), 'thumb': cands[cid]['thumb'],
             'must_find': list(scores[cid].get('must_find') or [])} for cid in ids]


def highlight_count(moments: dict) -> int:
    cands = {c['id'] for c in moments['candidates']}
    return sum(1 for cid, sc in moments.get('scores', {}).items() if sc.get('kind') != 'routine' and cid in cands)


def override_key(group: dict) -> str:
    return f'{group["process"]}|{group["members"][0]}'


def _apply(group: dict, override: dict, scores: dict, clip_max: float) -> bool:
    if override.get('dropped'):
        group['dropped'] = True
        return True
    cid = override.get('pick')
    if cid not in group['members']:
        return False
    group.pop('dropped', None)
    group['pick'] = cid
    group['clip_s'] = min(float(clip_max), scores[cid]['out'] - scores[cid]['in'])
    return True


def apply_overrides(groups: list[dict], overrides: dict, scores: dict, clip_max: float) -> list[str]:
    by_key = {override_key(g): g for g in groups}
    return [key for key, override in overrides.items()
            if key not in by_key or not _apply(by_key[key], override, scores, clip_max)]


def group_project(root: Path) -> dict:
    root = Path(root)
    brief = read_json(root / 'brief.json')
    probe = read_json(root / 'probe.json')
    moments = read_json(root / 'moments.json')
    clip_s = defaults()['types'][brief.get('type', 'trip')]['routine_clip_s']
    moments['groups'] = group_routine(moments, probe, clip_s)
    unmatched = apply_overrides(moments['groups'], moments.get('group_overrides', {}),
                                moments['scores'], clip_s[1])
    for key in unmatched:
        print(f'warning: group override {key} matches no group; kept, not applied', file=sys.stderr)
    moments['must_find'] = must_find_table(brief, moments)
    write_output(root, 'moments.json', moments, overwrite=True)
    return moments


SCORE_INTS = ('people', 'emotion', 'view', 'detail', 'brief_match')
SCORE_ENUMS = {'quality': ('good', 'fair', 'poor'), 'kind': ('highlight', 'routine')}
SCORE_FIELDS = SCORE_INTS + tuple(SCORE_ENUMS) + ('process', 'desc', 'in', 'out', 'must_find')


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def score_problems(score: dict, must_ids: set[str]) -> list[str]:
    if not isinstance(score, dict):
        return ['not an object']
    problems = [f'missing {f}' for f in SCORE_FIELDS if f not in score]
    for f in SCORE_INTS:
        if f in score and not (isinstance(score[f], int) and not isinstance(score[f], bool)
                               and 0 <= score[f] <= 5):
            problems.append(f'{f} must be an integer 0-5')
    for f, allowed in SCORE_ENUMS.items():
        if f in score and score[f] not in allowed:
            problems.append(f'{f} must be one of {"/".join(allowed)}')
    if 'process' in score and not (score['process'] is None or isinstance(score['process'], str)):
        problems.append('process must be a string or null')
    if 'desc' in score and not isinstance(score['desc'], str):
        problems.append('desc must be a string')
    if 'in' in score and 'out' in score:
        if not (_num(score['in']) and _num(score['out']) and 0 <= score['in'] < score['out']):
            problems.append('in/out must be numbers with 0 <= in < out')
    if 'must_find' in score:
        mf = score['must_find']
        if not isinstance(mf, list):
            problems.append('must_find must be a list')
        else:
            unknown = [m for m in mf if m not in must_ids]
            if unknown:
                problems.append(f'must_find has unknown ids {unknown}')
    return problems


def pending_ids(moments: dict) -> list[str]:
    scores = moments.get('scores', {})
    return [c['id'] for c in moments['candidates'] if c['id'] not in scores]


def process_labels(moments: dict) -> list[str]:
    return sorted({sc['process'] for sc in moments.get('scores', {}).values()
                   if isinstance(sc, dict) and isinstance(sc.get('process'), str)})


def batch_input(moments: dict, probe: dict, ids: list[str]) -> dict:
    durations = {c['file']: c['duration'] for c in probe['clips']}
    cands = {c['id']: c for c in moments['candidates']}
    rows = [{'id': cid, 'file': cands[cid]['file'], 't': cands[cid]['t'], 'thumb': cands[cid]['thumb'],
             'duration': durations.get(cands[cid]['file'])} for cid in ids]
    return {'candidates': rows, 'process_labels': process_labels(moments)}


def pending_batches(root: Path, batch: int) -> list[tuple[Path, Path, list[str]]]:
    root = Path(root)
    moments = read_json(root / 'moments.json')
    probe = read_json(root / 'probe.json')
    ids = pending_ids(moments)
    scores_dir = cache_dir(root) / 'scores'
    scores_dir.mkdir(parents=True, exist_ok=True)
    batches = []
    for chunk in (ids[i:i + batch] for i in range(0, len(ids), batch)):
        inputs = scores_dir / f'input-{chunk[0]}.json'
        inputs.write_text(json.dumps(batch_input(moments, probe, chunk), ensure_ascii=False) + '\n')
        scores_path = scores_dir / f'batch-{chunk[0]}.json'
        scores_path.unlink(missing_ok=True)
        batches.append((scores_path, inputs, chunk))
    return batches


DESC_MAX = 80


def _clip_keys(probe: dict) -> dict[str, str]:
    return {c['file']: f'f{n}' for n, c in enumerate(probe['clips'], 1)}


def _candidate_line(cid: str, cand: dict, sc: dict, key: str) -> str:
    kind = 'R' if sc.get('kind') == 'routine' else 'H'
    marks = '/'.join(str(sc.get(f, 0)) for f in ('people', 'emotion', 'view', 'detail', 'brief_match'))
    desc = '' if kind == 'R' else sc.get('desc', '')[:DESC_MAX]
    return (f'{cid} {key} {_fmt(cand["t"])} {_fmt(sc["in"])}-{_fmt(sc["out"])} r{_fmt(rank(sc))} {kind} {marks} '
            f'{sc.get("quality")} {",".join(sc.get("must_find") or []) or "-"} | {sc.get("process") or "-"} | {desc}')


def digest_text(brief: dict, probe: dict, moments: dict) -> str:
    btype = brief.get('type', 'trip')
    tcfg = defaults()['types'][btype]
    target = brief.get('target_min') or tcfg['target_min']
    keys = _clip_keys(probe)
    lut = moments.get('lut', {})
    scores = moments.get('scores', {})
    cands = {c['id']: c for c in moments['candidates']}
    scored = sorted((cid for cid in scores if cid in cands), key=lambda cid: -rank(scores[cid]))
    lines = [f'# video-summary digest · type {btype} · target_min {target[0]}-{target[1]} · '
             f'routine_clip_s {_fmt(tcfg["routine_clip_s"][0])}-{_fmt(tcfg["routine_clip_s"][1])} · '
             f'{len(scored)} scored of {len(cands)} candidates',
             '', '## Clips: key file duration_s created lut', '']
    lines += [f'{keys[c["file"]]} {c["file"]} {_fmt(c["duration"])} {c.get("created", "-")} '
              f'{"lut" if lut.get(c["file"]) else "-"}' for c in probe['clips']]
    lines += ['', '## Must-find: id status | required (best overall, best per other clip) | extras | text', '']
    for row in moments.get('must_find', []):
        required = ', '.join(f'{cid} {keys.get(cands[cid]["file"], "?")} {_fmt(scores[cid]["in"])}-'
                             f'{_fmt(scores[cid]["out"])}' for cid in row.get('required', []))
        lines.append(f'{row["id"]} {row["status"]} | required {required or "-"} | '
                     f'extras {" ".join(row.get("extras", [])) or "-"} | {row["text"]}')
    lines += ['', '## Groups: id pick clip-key in clip_s · members · process (DROPPED = leave out)', '']
    for g in moments.get('groups', []):
        pick = scores[g['pick']]
        flag = 'DROPPED ' if g.get('dropped') else ''
        lines.append(f'{g.get("id")} {flag}pick {g["pick"]} {keys.get(cands[g["pick"]]["file"], "?")} '
                     f'in {_fmt(pick["in"])} clip_s {_fmt(g["clip_s"])} · {len(g["members"])} members · {g["process"]}')
    lines += ['', '## Candidates by rank: id clip-key t in-out rank H|R people/emotion/view/detail/brief_match '
                  'quality must_find | process | desc (highlights only)', '']
    lines += [_candidate_line(cid, cands[cid], scores[cid], keys.get(cands[cid]['file'], '?')) for cid in scored]
    return '\n'.join(lines) + '\n'


def digest_project(root: Path) -> Path:
    root = Path(root)
    text = digest_text(read_json(root / 'brief.json'), read_json(root / 'probe.json'),
                       read_json(root / 'moments.json'))
    path = cache_dir(root) / 'digest.txt'
    path.write_text(text)
    return path


def merge_project(root: Path, new_scores: dict) -> int:
    root = Path(root)
    brief = read_json(root / 'brief.json')
    moments = read_json(root / 'moments.json')
    if not isinstance(new_scores, dict):
        raise ValueError('scores must be a JSON object {candidate_id: score}')
    known = {c['id'] for c in moments['candidates']}
    must_ids = {m['id'] for m in brief.get('must_find', [])}
    problems = []
    for cid, sc in new_scores.items():
        if cid not in known:
            problems.append(f'{cid}: unknown candidate')
            continue
        problems += [f'{cid}: {p}' for p in score_problems(sc, must_ids)]
    if problems:
        raise ValueError('rejected, nothing merged:\n' + '\n'.join(problems))
    moments.setdefault('scores', {}).update(new_scores)
    write_output(root, 'moments.json', moments, overwrite=True)
    return len(pending_ids(moments))


def pick_project(root: Path, gid: str, cid: str | None) -> dict:
    root = Path(root)
    brief = read_json(root / 'brief.json')
    moments = read_json(root / 'moments.json')
    groups = moments.get('groups', [])
    gid = gid if gid.startswith('g') else f'g{gid}'
    group = next((g for g in groups if g.get('id') == gid), None)
    if group is None:
        raise ValueError(f'no group {gid}; groups: {", ".join(g.get("id", "?") for g in groups)}')
    if cid is not None and cid not in group['members']:
        raise ValueError(f'{cid} is not a member of {gid}: {", ".join(group["members"])}')
    override = {'dropped': True} if cid is None else {'pick': cid}
    clip_max = defaults()['types'][brief.get('type', 'trip')]['routine_clip_s'][1]
    _apply(group, override, moments['scores'], clip_max)
    moments.setdefault('group_overrides', {})[override_key(group)] = override
    write_output(root, 'moments.json', moments, overwrite=True)
    return group


def _read_source(src: str) -> str:
    return sys.stdin.read() if src == '-' else Path(src).expanduser().read_text()


def main() -> None:
    parser = argparse.ArgumentParser(description='Group routine moments and build the shortlist')
    parser.add_argument('project')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('group', help='group routine moments and refresh the must-find table')
    sl = sub.add_parser('shortlist', help='print the shortlist')
    sl.add_argument('--top', type=int, default=None, help='default: max(40, target_max_min * 10)')
    mg = sub.add_parser('merge', help='merge frame-analyst scores {id: score}')
    mg.add_argument('scores', help='JSON file, or - for stdin')
    pd = sub.add_parser('pending', help='write batch inputs; print "<scores path>\\t<input path>\\t<ids>" per batch')
    pd.add_argument('--batch', type=int, default=40)
    uc = sub.add_parser('uncovered', help='list scored highlights no clip covers, by rank')
    uc.add_argument('clips', help='clips.json array file, or - for stdin')
    sub.add_parser('digest', help='write the compact clip-editor digest to the cache; print its path')
    pk = sub.add_parser('pick', help='swap a group pick to another member, or drop the group')
    pk.add_argument('group', help='group id as in the shortlist, e.g. g3')
    pk.add_argument('candidate', help='member candidate id, or drop')
    args = parser.parse_args()
    root = Path(args.project).expanduser()
    if args.command == 'merge':
        try:
            data = json.loads(_read_source(args.scores))
            remaining = merge_project(root, data)
        except (OSError, ValueError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            sys.exit(1)
        print(f'{len(data)} merged, {remaining} unscored')
        return
    if args.command == 'pending':
        for scores_path, inputs, ids in pending_batches(root, args.batch):
            print(f'{scores_path}\t{inputs}\t{" ".join(ids)}')
        return
    if args.command == 'uncovered':
        try:
            moments = read_json(root / 'moments.json')
            rows = uncovered(moments, json.loads(_read_source(args.clips)))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            sys.exit(1)
        print(f'{len(rows)} of {highlight_count(moments)} scored highlights not covered by the clips')
        for r in rows:
            print(f'- {r["id"]} · rank {_fmt(r["rank"])} · {",".join(r["must_find"]) or "-"} · {r["file"]} · '
                  f'{_fmt(r["in"])}–{_fmt(r["out"])} · {r["desc"]} · {r["thumb"]}')
        return
    if args.command == 'digest':
        print(digest_project(root))
        return
    if args.command == 'pick':
        try:
            group = pick_project(root, args.group, None if args.candidate == 'drop' else args.candidate)
        except (OSError, ValueError, KeyError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            sys.exit(1)
        verb = 'dropped' if args.candidate == 'drop' else f'pick {group["pick"]} {_fmt(group["clip_s"])}s'
        print(f'{group["id"]} {group["process"]}: {verb}')
        return
    if args.command == 'group':
        moments = group_project(root)
        missing = sum(1 for r in moments['must_find'] if r['status'] != 'found')
        print(f'{len(moments["groups"])} groups, {missing} must-find not found')
        return
    print(shortlist_md(read_json(root / 'brief.json'), read_json(root / 'probe.json'),
                       read_json(root / 'moments.json'), args.top), end='')


if __name__ == '__main__':
    main()
