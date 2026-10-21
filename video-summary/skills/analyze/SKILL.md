---
name: analyze
description: Analyzes camera footage for a video-summary project — probes every clip, samples candidate moments from scene changes, loud peaks and a baseline, scores them with video-summary:frame-analyst in batches and groups repetitive routine scenes into moments.json. Use when a project has brief.json and needs its footage analysed, scoring resumed or new candidates scored. Not for choosing clips or reviewing the shortlist — use video-summary:plan.
argument-hint: "[project-folder]"
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/*) Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/*) Read Glob
---

# Analyze footage

Project folder: $ARGUMENTS

Recall first: the scoring must surface every moment the user could remember. Thumbnails and
caches go to `~/.cache/video-summary/<slug>/`; only `probe.json` and `moments.json` are written
into the project folder, by the scripts. Quote every path.

## Checklist

Copy and track:

```
- [ ] 1. Preconditions: brief.json exists; existing probe/moments handled
- [ ] 2. probe.py
- [ ] 3. sample.py
- [ ] 4. Score: frame-analyst batches of ≤40, waves of ≤5, merge each wave; halve failing batches
- [ ] 5. moments.py group
- [ ] 6. Report counts; validate → fix → re-run
```

## 1. Preconditions

- `brief.json` must exist (Glob). If not, stop: the brief comes from `video-summary:start`.
- If `probe.json` or `moments.json` already exist, do not pass `--overwrite` on your own.
  `moments.json` holds all scores: `sample.py --overwrite` discards them. Tell the user what
  exists and ask; to resume scoring, skip to step 4.

## 2. Probe

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/probe.py" "<project>"
```

Prints one row per clip (duration, fps, size, audio channels, created) and the chosen frame
(majority shape, 2560 long side, majority fps). Tell the user the clip count, total footage
length and the frame; if some clips have another shape, say they will be fitted with a blurred
fill, never cropped. `exists, use --overwrite` → see step 1.

## 3. Sample

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sample.py" "<project>"
```

Scene detection costs about 20 s per minute of 4K footage; for more than ~30 min of footage tell
the user the estimate first and run it in the background. Output: `N candidates: {scene, loud,
baseline}`. A frame that cannot be decoded is skipped, not fatal: `skipped N timestamps (no
thumbnail):` lists each `file @ t` with the ffmpeg error. Tell the user; a clip with many skips is
likely damaged (report it, never move or delete it). Files, base names or folders listed in
`brief.json` `force_exclude` are not sampled: `not sampled (force_exclude): ...` names them; tell
the user.

## 4. Score with video-summary:frame-analyst

Get the unscored ids in batches of ≤40. `pending` writes one compact input file per batch (ids,
clip, time, thumb, clip duration, the process labels already used) into the cache:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/moments.py" "<project>" pending --batch 40
```

Each line is `<scores path><TAB><input path><TAB><ids>`, e.g.
`/Users/me/.cache/video-summary/squash/scores/batch-c0001.json	/Users/me/.cache/video-summary/squash/scores/input-c0001.json	c0001 ... c0040`
(paths are absolute and may contain spaces).

Dispatch `video-summary:frame-analyst` (Agent tool, that exact `subagent_type`) once per line,
**at most 5 in parallel** (one wave). Each prompt carries only data:

```
brief.json: <project>/brief.json
Batch input: <input path from that line>
Output path: <scores path from that line>
```

The agent writes its JSON object to that path and replies only `ok <N> ids <path>`. Its scores
never pass through this conversation; do not Read or retype them. When the whole wave has
replied, merge each batch file, then run `pending` again before the next wave, so its input
files carry the process labels just merged. `pending` deletes any old scores file at the paths
it prints, so never run it while a wave's files are unmerged:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/moments.py" "<project>" merge "<scores path>"
```

Output: `40 merged, 312 unscored`. Exit 1 rejects the whole batch and names each problem
(`c0007: missing desc`, `c0012: unknown candidate`, `c0020: must_find has unknown ids ['m9']`);
a missing or unparsable file is also exit 1. Re-dispatch that batch once to the same paths with
the error lines appended (`Previous output was rejected: ...`) and merge again. If it fails a
second time, note its errors and continue with the other batches; `pending` keeps listing those
ids. Never write or edit a scores file yourself.

Repeat `pending` → wave → merge until `pending` lists only batches that failed twice. Then halve:
`pending --batch 20`, dispatch and merge; still failing → `--batch 10`, then `--batch 5`. Smaller
batches isolate the bad candidate (often an unreadable thumbnail). If ids still fail at
`--batch 5`, stop retrying: tell the user how many stay unscored with their errors, and that
`moments.py shortlist` lists each one (file @ t and thumbnail) so plan can go ahead once they
acknowledge it. Tell the user progress between waves (`wave 3/8 merged`).

## 5. Group routine scenes

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/moments.py" "<project>" group
```

Output: `N groups, M must-find not found`. Grouping collapses repeated routine (walking, transit,
queueing) into one short clip per process; the user reviews and can veto these in
`video-summary:plan`. Re-running `group` rebuilds `groups` (ids `g1`, `g2`, … in time order) and
the must-find table, and re-applies the user's earlier swaps and drops from `group_overrides`;
a `warning: group override ... matches no group` on stderr means one no longer fits — tell the
user.

## 6. Report

Tell the user: clips and footage length, frame, candidates by source, highlights vs routine,
groups, and every must-find id with found / not found. Not-found items are the next stage's
first job, so name them plainly. Then continue with `video-summary:grade` (the LUT decision comes
before planning), or return to `video-summary:start` if it invoked you.

Field meanings and the rank formula are in
[references/schemas.md](references/schemas.md#momentsjson).

## Validate → fix → re-run

1. `moments.py "<project>" pending` prints nothing, or only ids that failed at `--batch 5` and
   were reported to the user.
2. `moments.py "<project>" group` exits 0.

If `pending` still lists other ids, score and merge them (step 4) and re-check. If a script fails,
read its error: a probe failure on one clip usually means a damaged or partial file — report it
by name and never move, rename or delete it. Fix, re-run the failing command, then the check.
