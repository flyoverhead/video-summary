import json
import re
from pathlib import Path

GRADERS = Path(__file__).resolve().parent.parent / 'video-summary' / 'evals'


def pattern(case: str, grader: str) -> re.Pattern:
    text = (GRADERS / case / 'graders' / f'{grader}.md').read_text()
    raw = re.search(r"^input_match: '(.*)'$", text, re.M).group(1)
    return re.compile(raw)


def serialized(command: str) -> str:
    return json.dumps({'command': command})


NO_SET = pattern('outcome-grade-asks-before-apply', 'no-set')
PREVIEWED = pattern('outcome-grade-asks-before-apply', 'previewed')
NO_CLIPS = pattern('outcome-plan-lists-missing', 'no-clips-write')

SET_BAD = [
    'python3 "/x/scripts/lut.py" "/p" set --all true',
    'python3 /x/lut.py /p set --all false "a/b.MP4=true"',
    "jq '.lut={}' moments.json > moments.json",
    'echo {} >> "/p/moments.json"',
    "sed -i '' 's/a/b/' moments.json",
    'sed -i.bak "s/a/b/" "/p/moments.json"',
    'jq . x.json | tee "/p/moments.json"',
    'jq . x.json | sponge moments.json',
    'cp /tmp/new.json "/p/moments.json"',
    'mv /tmp/new.json moments.json',
    'cp /tmp/new.json moments.json 2>&1',
    'python3 -c "import json; json.dump({}, open(\'moments.json\', \'w\'))"',
]
SET_OK = [
    'jq . moments.json',
    'cat moments.json',
    'cat "/p/moments.json"',
    'python3 -c "import json; print(json.dumps(json.load(open(\'moments.json\'))))"',
    'cp moments.json /tmp/backup.json',
    'python3 -c "import json; print(json.load(open(\'moments.json\')))"',
    'python3 "/x/lut.py" "/p" preview a.MP4 1.0',
    'python3 "/x/lut.py" "/p" detect',
    'ls -la; used mv-tool --help',
]
CLIPS_BAD = [
    'python3 "/x/scripts/project.py" write "/p" clips.json - <<\'JSON\'\n[{"file": "a"}]\nJSON',
    'python3 /x/project.py write /p clips.json --overwrite',
    'echo "[]" > clips.json',
    'cat x >> "/p/clips.json"',
    "sed -i '' 's/a/b/' clips.json",
    'cp /tmp/c.json "/p/clips.json"',
    'cp /tmp/c.json clips.json 2>&1',
    'tee clips.json < /tmp/c.json',
    'python3 -c "open(\'clips.json\', \'w\').write(\'[]\')"',
]
CLIPS_OK = [
    'jq . clips.json',
    'cat clips.json',
    'python3 -c "import json; print(json.dumps(json.load(open(\'clips.json\'))))"',
    'cp clips.json /tmp/c.json',
    'python3 "/x/scripts/moments.py" "/p" shortlist',
    'python3 "/x/scripts/project.py" write "/p" brief.json -',
]


def test_no_set_matches_writes():
    for cmd in SET_BAD:
        assert NO_SET.search(serialized(cmd)), cmd


def test_no_set_ignores_reads():
    for cmd in SET_OK:
        assert not NO_SET.search(serialized(cmd)), cmd


def test_previewed_matches_preview_only():
    assert PREVIEWED.search(serialized('python3 "/x/lut.py" "/p" preview a.MP4 1.0'))
    assert not PREVIEWED.search(serialized('python3 "/x/lut.py" "/p" detect'))


def test_no_clips_write_matches_writes():
    for cmd in CLIPS_BAD:
        assert NO_CLIPS.search(serialized(cmd)), cmd


def test_no_clips_write_ignores_reads():
    for cmd in CLIPS_OK:
        assert not NO_CLIPS.search(serialized(cmd)), cmd


def test_rescan_example_clip_in_fixture():
    grader = (GRADERS / 'outcome-plan-lists-missing' / 'graders' / 'rescan.md').read_text()
    setup = (GRADERS / 'outcome-plan-lists-missing' / 'setup.sh').read_text()
    assert '22.08/DJI_0001_D.MP4' in grader and '22.08/DJI_0001_D.MP4' in setup


def test_eval_fixtures_follow_contracts():
    for setup in GRADERS.glob('*/setup.sh'):
        text = setup.read_text()
        assert set(re.findall(r'"shape": "(\w+)"', text)) <= {'square', 'wide', 'vertical'}, setup
        assert set(re.findall(r'"quality": (\d+)', text)) <= {'40', '60', '75'}, setup
