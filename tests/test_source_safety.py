import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / 'video-summary' / 'scripts'
ALLOWED_NEW = {'brief.json', 'probe.json', 'moments.json', 'clips.json', 'config.json', 'SUMMARY.md',
               'SUMMARY_VIDEO.mp4', 'SUMMARY_VIDEO.draft.mp4'}


def snapshot(root: Path) -> dict:
    entries = {}
    for path in sorted(root.rglob('*')):
        rel = str(path.relative_to(root))
        st = path.stat()
        if path.is_dir():
            entries[rel] = ('dir', st.st_mtime_ns)
        else:
            entries[rel] = (st.st_size, st.st_mtime_ns, hashlib.sha1(path.read_bytes()).hexdigest())
    return entries


def test_pipeline_only_adds_allowlisted_files(project, tmp_path):
    env = {**os.environ, 'HOME': str(tmp_path / 'home')}

    def cli(script, *args, stdin=None):
        proc = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], input=stdin,
                              capture_output=True, text=True, env=env)
        assert proc.returncode == 0, (script, args, proc.stdout, proc.stderr)
        return proc.stdout

    before = snapshot(project)
    brief = {'type': 'trip', 'source': str(project), 'description': 'd', 'timeline': 't', 'tone': 'calm',
             'must_find': [{'id': 'm1', 'text': 'pier'}], 'keep_memories': [], 'target_min': [1, 2],
             'quality': 60, 'music': None, 'force_include': [], 'force_exclude': []}
    cli('project.py', 'write', project, 'brief.json', '-', stdin=json.dumps(brief))
    cli('probe.py', project)
    cli('sample.py', project)
    batches = [line.split('\t') for line in cli('moments.py', project, 'pending').splitlines()]
    for scores_path, inputs, _ in batches:
        cands = json.loads(Path(inputs).read_text())['candidates']
        scores = {c['id']: {'people': 1, 'emotion': 1, 'view': 1, 'detail': 1, 'brief_match': 0,
                            'quality': 'good', 'kind': 'routine' if n % 2 else 'highlight',
                            'process': 'walking' if n % 2 else None, 'desc': 'x',
                            'in': 0.0, 'out': min(1.0, c['duration']), 'must_find': []}
                  for n, c in enumerate(cands)}
        Path(scores_path).write_text(json.dumps(scores))
        cli('moments.py', project, 'merge', scores_path)
    cli('moments.py', project, 'group')
    cli('moments.py', project, 'digest')
    cli('lut.py', project, 'set', '--all', 'false', '22.08/square.MP4=true')
    probe = json.loads((project / 'probe.json').read_text())
    clips = [{'file': c['file'], 'start': 0.5, 'duration': 1.0, 'label': 'Pier', 'lut': c['file'] == '22.08/square.MP4'}
             for c in probe['clips']]
    tmp = Path(cli('moments.py', project, 'digest').strip()).parent / 'render'
    config = {'src': str(project), 'out': str(project / 'SUMMARY_VIDEO.mp4'), 'tmp': str(tmp),
              'frame': {'shape': 'square', 'width': 320, 'height': 320, 'fps': 25.0}, 'quality': 60,
              'audio_br': '192k', 'lut': None, 'music': None, 'draft_long_side': 160}
    cli('project.py', 'write', project, 'clips.json', '-', stdin=json.dumps(clips))
    cli('project.py', 'write', project, 'config.json', '-', stdin=json.dumps(config))
    cli('project.py', 'write', project, 'SUMMARY.md', '-', stdin='# Trip\n')
    cli('render_summary.py', project, '--draft')
    cli('render_summary.py', project)
    assert 'OK' in cli('verify.py', project)

    after = snapshot(project)
    added = set(after) - set(before)
    assert added == ALLOWED_NEW
    assert set(before) <= set(after)
    changed = {k for k in before if k != '.' and before[k] != after[k] and before[k][0] != 'dir'}
    assert changed == set()
    subdirs = {k for k, v in before.items() if v[0] == 'dir'}
    assert {k for k in subdirs if before[k] != after[k]} == set()
    assert str(tmp_path / 'home') in str(tmp) and project.resolve() not in tmp.resolve().parents
