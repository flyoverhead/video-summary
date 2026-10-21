---
name: start
description: Starts a video-summary project from a camera footage folder — checks for existing outputs (resume or redo), interviews the user about tone, must-find moments and memories to keep, writes brief.json, then runs analyze, grade, plan, render and verify in order. Use when the user wants a summary, highlight or trip video made from their clips. Not for one stage on its own — use video-summary:analyze, video-summary:plan, video-summary:grade, video-summary:render or video-summary:verify.
argument-hint: "[footage-folder] [what the video is about]"
disable-model-invocation: true
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/*) Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/*) Read Glob Skill
---

# Start a video summary

Request: $ARGUMENTS

The user's worst outcome is a moment they remember missing from the video. The second worst is
a changed source folder. Every stage below keeps both in view: recall over brevity, and nothing
written into the footage folder except the plugin's own outputs, through the bundled scripts.

Scripts run as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py" ...`. Quote every project path:
trip folders often contain spaces.

## Checklist

Copy and track:

```
- [ ] 1. Resolve the project folder; list existing outputs; ask resume or redo
- [ ] 2. Fill the inputs table from the prompt; one numbered question for the rest
- [ ] 3. Write brief.json (project.py write)
- [ ] 4. video-summary:analyze
- [ ] 5. video-summary:grade
- [ ] 6. video-summary:plan
- [ ] 7. Hand off render (user types /video-summary:render), which ends in video-summary:verify
```

## 1. Project folder and existing outputs

The project folder is the footage folder the user names (date subfolders inside it are fine; one
run = one video). Expand `~`. If none is given, it is question 1 of step 2.

Before anything else, Glob the folder for the outputs: `brief.json`, `probe.json`,
`moments.json`, `clips.json`, `config.json`, `SUMMARY.md`, `SUMMARY_VIDEO.mp4`,
`SUMMARY_VIDEO.draft.mp4`. If any exist, list them with what they imply and ask one numbered
question:

```
Found in <folder>: brief.json, probe.json, moments.json (412 candidates, 380 scored), clips.json.
1. Resume from the first unfinished stage (scoring the 32 unscored candidates), or redo from the
   interview? Redo keeps nothing silently: each file is shown as a diff before it is replaced.
```

Resume picks the first stage whose output is missing or incomplete: no `brief.json` → interview;
no `probe.json` or unscored candidates (`moments.py "<project>" pending` prints any, unless the
user already acknowledged them as unscorable) → analyze;
no `lut` decisions in `moments.json` → grade; no `clips.json` → plan; no `SUMMARY_VIDEO.mp4` →
render. On resume, Read `brief.json` and carry it forward instead of re-asking.

Redo of `probe.json` or `moments.json` means `--overwrite` on `probe.py` / `sample.py`, which
discards all scores. Say so and get a yes for that specifically.

## 2. Interview

Fill this table from the prompt and any earlier messages. Ask only for what is still open, in
**one** numbered message; the user answers `1.X 2.Y 3.Z`.

| Input | Default | Notes |
|---|---|---|
| Source folder | ask | May contain date subfolders |
| Type | `trip` | trip / sport / everyday / other; do not ask when the prompt implies it |
| Description & general timeline | ask | Route, places, order of events |
| Emotional tone of the result | ask | e.g. calm and nostalgic vs energetic; drives pacing |
| Moments to catch most | ask | Free text; each becomes a must-find target |
| Memories to keep for future viewing | ask | People, places, small details; boosts scoring |
| Target duration | by type: trip 10–15, sport 3–6, everyday 3–8, other 5–10 min | |
| Music | none | Ask only if the user mentions music; then file path + duck / replace |
| Quality | standard (60) | draft 40 / high 75 (hevc_videotoolbox -q:v: higher is better) |
| Force include / exclude | none | File names or moments |

Always ask tone, moments to catch and memories to keep unless the prompt already answers them;
they are what this plugin optimises for. Number only the open inputs: never a question about a
folder the prompt named (state what you found in it instead) or about a type the prompt implies.
State the defaults as one plain line in the same message, so the user can override them in the
same reply. Example:

```
Defaults: type trip, 10–15 min, quality standard (60), no music, nothing forced in or out.
1. What happened, in order? Places, route, who was there.
2. What should the video feel like when you watch it in five years? (e.g. calm and nostalgic,
   energetic, funny)
3. Which moments must be in it? List each one; I will search for every item and tell you
   which I could not find.
4. What small things do you want to remember? People, a dish, a view, a sign, a sound.
```

Music: off by default. If the user brings it up, ask for the file path and the mode: **duck**
(camera sound kept, music lower underneath) or **replace** (music only). When the user picks
replace, warn in the same reply that it drops all camera sound (voices, laughter, the moment's
own noise) for the whole video, and confirm. Check the file exists with Glob; it stays where it
is.

## 3. Write brief.json

Build the object exactly as in [schemas.md](../analyze/references/schemas.md#briefjson). Split
"moments to catch" into one `must_find` entry per moment (`m1`, `m2`, …, in the user's order,
their own words), and "memories" into `keep_memories` strings. `source` is the absolute folder
path; `target_min` is `[lo, hi]` in minutes.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/project.py" write "<project>" brief.json - <<'JSON'
{"type": "trip", "source": "/Users/me/Movies/camera/hong-kong", ...}
JSON
```

Exit 1 means `brief.json` exists and differs: show the printed diff, ask, then re-run with
`--overwrite`. Exit 2 is invalid JSON or a missing folder; fix and re-run. Read back the summary
line (`created:` / `overwritten:` / `unchanged:`).

## 4–6. Analyze, grade, plan

Invoke each with the Skill tool, passing the project folder, and finish one before the next:

1. `video-summary:analyze` — probe, sample, score, group. Long footage takes a while; tell the
   user the candidate count and batch count before scoring starts.
2. `video-summary:grade` — before/after LUT preview, the user's all / some / none.
3. `video-summary:plan` — shortlist, must-find check with re-scan, group vetoes, the clip table,
   then `clips.json`, `config.json`, `SUMMARY.md` (with the LUT decision in it).

A stage that fails stops the chain: report its error, fix inside that stage, and re-run it
before moving on. Never skip the shortlist or the LUT question to save time.

## 7. Render hand-off

`video-summary:render` starts a long encode and is user-invoked only. Close with:

> Grade and plan are done. Run `/video-summary:render <project>` to see the pre-render summary,
> make a draft and then the final video; it finishes with `video-summary:verify`.

## Validate → fix → re-run

After step 3 and after each stage, check the stage's own output before continuing:

1. `brief.json` written (`project.py` exit 0) and every must-find from the interview is in it.
2. `moments.py "<project>" pending` prints nothing after analyze, or only ids analyze reported
   as unscorable and the user acknowledged.
3. `moments.json` `lut` has an entry per clip after grade; `clips.json`, `config.json` and
   `SUMMARY.md` exist after plan.

If a check fails, return to that stage, fix the cause (not the symptom), and run the check
again. Do not hand off to render while any check fails.
