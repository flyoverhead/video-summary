---
name: plan
description: Plans the cut of a video-summary project — shows the ranked shortlist and the must-find found/not-found table, re-scans likely clips for missed moments, applies the user's vetoes and swaps of routine groups, drafts clips.json with video-summary:clip-editor and, once the user confirms the clip table, writes clips.json, config.json and SUMMARY.md. Use when moments.json is scored and the cut needs choosing, or to fix a cut after a render. Not for scoring footage — use video-summary:analyze.
argument-hint: "[project-folder]"
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/*) Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/*) Read Glob
---

# Plan the cut

Project folder: $ARGUMENTS

This is the main guard against the worst outcome, a missed moment. Every drop is shown to the
user before anything is written. Quote every path.

## Checklist

Copy and track:

```
- [ ] 1. Show the shortlist and the must-find table
- [ ] 2. Offer a re-scan for every not-found must-find; re-score, re-group, re-show
- [ ] 3. Routine groups: user vetoes or swaps picks (moments.py pick)
- [ ] 4. Dispatch video-summary:clip-editor
- [ ] 5. Show the clip table; adjust until the user confirms
- [ ] 6. Write clips.json, config.json, SUMMARY.md (project.py write)
```

Preconditions: `brief.json`, `probe.json`, `moments.json` exist,
`moments.py "<project>" pending` prints nothing (else `video-summary:analyze`) or the user has
acknowledged the shortlist's `## Unscored` list (ids analyze could not score), and
`moments.json` `lut` has the user's LUT decision (else `video-summary:grade` first, so the cut
and `SUMMARY.md` carry it).

## 1. Shortlist

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/moments.py" "<project>" shortlist
```

The default `--top` is max(40, target max minutes × 10). When more highlights exist, it prints
`N more highlights below rank R not shown — rerun with --top M`: always pass that line on to the
user and offer the full list.

Show it to the user grouped by timeline section (use `brief.json` `timeline` to name sections;
`probe.json` `created` orders the clips). Keep each highlight's thumbnail path so the user can
open it. Then the routine groups (`- g3 · 12 clips · walking through market → 1 × 8s (...)`) and
the must-find table. Dropped groups show `DROPPED`. The must-find `best match` column is
`file @ t` plus a thumbnail path so the user can open the frame and confirm it is the moment;
keep the ids. If an `## Unscored` section is present, show it in full (file @ t and thumbnail per
id): those moments cannot be in the cut. Ask the user to acknowledge it, or to open the
thumbnails and name any to force-include, before step 4.

## 2. Not-found must-finds

For each must-find with status **not found**, pick the likely clips from the brief's timeline,
the clip `created` times and the descriptions of neighbouring candidates. Ask in one numbered
message:

```
2 must-find moments were not found:
1. m2 "the cat on the temple steps" — re-scan 22.08/DJI_0031_D.MP4 and DJI_0032_D.MP4 every 2 s?
2. m4 "sunset from the ferry" — which part of the day was it? I can re-scan the evening clips.
```

On a yes:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sample.py" "<project>" --rescan "22.08/DJI_0031_D.MP4" "22.08/DJI_0032_D.MP4" --every 2
```

Then score the new candidates exactly as `video-summary:analyze` step 4 (`moments.py pending`,
`video-summary:frame-analyst` batches ≤40, waves ≤5, `moments.py merge` per batch), run
`moments.py "<project>" group`, and show the must-find table and the routine groups again
(a re-group can change them; any `warning: group override` line goes to the user). Repeat while the user wants
to; a still-missing moment is reported, never hidden. If the user says it is not in the footage,
note that and move on.

## 3. Routine groups

Ask whether any collapse is wrong, in one numbered message listing the groups. The user can:

- swap the pick to another member: `moments.py "<project>" pick g3 c0142`
- drop the group from the cut: `moments.py "<project>" pick g3 drop` (marked dropped, ids never
  shift, so "drop g3 and g5" is two commands with those ids)
- keep a group's moment in full: add it to `brief.json` `force_include` (step 5 rules)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/moments.py" "<project>" pick g3 c0142
```

Each choice is stored in `moments.json` `group_overrides` and re-applied by every later
`moments.py group`. After any re-group, show the groups again and re-ask, since members can
change. Each group line ends with its `members` ids; each member's file, time and thumb are
in the digest (step 4) by id.

## 4. Draft with video-summary:clip-editor

Write the compact digest (clips, must-find, groups, one line per scored candidate; a fraction
of `moments.json`, which is too large to Read on a long trip). It prints the digest path:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/moments.py" "<project>" digest
```

Dispatch `video-summary:clip-editor` (Agent tool, that exact `subagent_type`) with paths only:

```
brief.json: <project>/brief.json
digest: <path printed by digest>
shapes.md: ${CLAUDE_PLUGIN_ROOT}/skills/start/references/shapes.md
```

Re-run `digest` before every dispatch: it reflects the current scores, groups and LUT.

It returns a `clips.json` array, then an editorial summary (type/tone, totals vs target,
must-find coverage, exclusions, force overrides, story arc). Parse the array; if it is not valid
JSON, re-dispatch once with the parse error.

## 5. Clip table

Show every clip, then the summary:

```
#  | File                     | Start → End   | Dur  | Label            | LUT
1  | 22.08/DJI_0001_D.MP4     | 10.0 → 18.0   | 8.0  | Old Town Square  | yes
...
Total: 74 clips, 12m 40s (target 10–15 min)
Must-find: m1 → #4, m2 → #19, m3 not in cut (force_exclude "selfie stick")
```

List what was excluded and why, and every force override. Pipe the drafted array on stdin
(never write a scratch file into the project) to list the scored highlights no clip covers (a
clip of the same file holds the frame time or half the window):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/moments.py" "<project>" uncovered - <<'JSON'
[{"file": "22.08/DJI_0001_D.MP4", "start": 10.0, "duration": 8.0, "label": "Old Town Square", "lut": true}]
JSON
```

It prints `63 of 210 scored highlights not covered by the clips`, then one line per highlight by
rank: `- c0042 · rank 14 · m2 · 22.08/DJI_0031_D.MP4 · 30–38 · desc · thumb`. Say the count
(`63 scored highlights are not in the cut — list them?`) and always name the lines that carry a
must-find id: they are must-find extras the editor left out; the required matches are in the
cut. On a yes, show the list as printed. Accept edits in the user's words
(`3 start at 12`, `drop 7`, `add 22.08/DJI_0040_D.MP4 30–42 as Night Market`, `label 2: Peak
Tram`), apply them to the array yourself, keep `start + duration` within the file's
`probe.json` duration, and re-show the changed rows plus the new total. If the total leaves the
target by more than 15 %, say so and offer: trim the longest clips, the user names cuts, or keep
it. Changes to `force_include` / `force_exclude` / target go into `brief.json` (step 6 rules),
then re-dispatch the editor. Loop until the user confirms the table.

## 6. Write the files

All three go through `project.py write`; a refusal (exit 1) prints the diff: show it, ask, then
re-run with `--overwrite`.

1. `clips.json` — the confirmed array.
2. `config.json` — per [schemas.md](../analyze/references/schemas.md#configjson): `src` the
   project folder, `out` `<project>/SUMMARY_VIDEO.mp4`, `tmp` the thumbnails' cache folder
   (parent of `thumbs/`) plus `/render`, `frame` from `probe.json`, `quality` from the brief,
   `audio_br` `"192k"`, `lut` `null` (bundled LUT), `music` from the brief with `"duck_db": -18`
   or `null`.
3. `SUMMARY.md` — the trip in words for later reading: title and dates, one section per timeline
   section with its clips (`#`, label, file, start, duration, one-line scene), the must-find
   coverage, then a short technical footer (frame, fps, quality, LUT clips, music).

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/project.py" write "<project>" clips.json - <<'JSON'
[{"file": "22.08/DJI_0001_D.MP4", "start": 10.0, "duration": 8.0, "label": "Old Town Square", "lut": true}]
JSON
```

LUT flags in `clips.json` come from `moments.json` `lut` (decided in `video-summary:grade`);
note the LUT clips in `SUMMARY.md`. Rendering is user-invoked: tell the user to run
`/video-summary:render <project>` (or return to `video-summary:start`).

## Validate → fix → re-run

1. Each `project.py write` exits 0 and prints `created:` / `overwritten:` / `unchanged:`.
2. Every found must-find id appears in the confirmed table or is listed with its reason, and
   `uncovered` lists no must-find id the user has not seen.
3. Every clip's `file` exists in `probe.json` and `start + duration` ≤ its duration.

On a failure, fix the array or the field it names, re-run the write, and re-check. Fixes after a
render come back here, not to analyze: edit the table, write `clips.json` again, render again.
