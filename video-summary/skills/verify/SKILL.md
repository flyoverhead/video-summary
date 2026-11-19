---
name: verify
description: Verifies a rendered video-summary output against its plan — duration vs clips.json, stereo audio, frame size and per-clip LUT flags from the per-output render manifest (for a pilot render, only the rendered clip range) via verify.py — reports the result, asks the user to spot-check and routes any fix back to planning. Use after a draft or final render, or when the user asks whether a summary video came out right. Not for changing the cut — use video-summary:plan.
argument-hint: "[project-folder] [--draft]"
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/*) Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/*) Read Glob
---

# Verify the output

Project folder: $ARGUMENTS

Read-only on the project: this skill inspects the output and the plan files and changes nothing there (only `prefs.py add`, outside the project, after approval, and the final clean-up of the project's cache folder under `~/.cache/video-summary`). Quote every
path.

## Checklist

Copy and track:

```
- [ ] 1. verify.py (add --draft for the draft)
- [ ] 2. Report
- [ ] 3. Spot-check question
- [ ] 4. Locate the user's timestamps, then fixes go to video-summary:plan, then a new render;
      offer to save a lasting rule (prefs.py add, only on approved wording)
- [ ] 5. Final render accepted: project.py clean, report its line (never after a draft)
```

## 1. Run the checks

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify.py" "<project>"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify.py" "<project>" --draft
```

It prints the facts, then `OK` (exit 0) or one `PROBLEM:` line per problem (exit 1), then one
`WARN:` line per QA finding. The QA scan decodes the whole output once, so it takes a while on a
long video; `--no-qa` skips it (the post-render hook always skips it).

```
Output:   /Users/me/Movies/camera/squash/SUMMARY_VIDEO.mp4
Duration: 12m 41s (761.3s)
Size:     1843.2 MB
OK
```

| Problem line | Meaning |
|---|---|
| `PROBLEM: output missing or empty: ...` | The render did not finish or wrote nothing |
| `PROBLEM: duration X differs from planned Y` | More than 5 s off the `clips.json` total |
| `PROBLEM: audio has N channels, expected 2` | Stereo upmix missing; see the render known issues |
| `PROBLEM: dimensions WxH differ from expected` | Frame not from `config.json` (draft: scaled to 720) |
| `PROBLEM: render manifest missing` / `manifest file list differs` | Output is from another plan; re-render |
| `PROBLEM: manifest LUT flags differ from clips.json` | LUT decision changed after the render |
| `PROBLEM: cannot check ...` | A plan file is malformed; fix it in `video-summary:plan` |
| `WARN: black 3:41.2–3:42.0 (#19 file @ 34.2s)` | Informational, never fails the check. Black frames at that output time, mapped to the clip and source time |
| `WARN: freeze ...` / `WARN: silence ...` | Same form: frozen picture (3 s or more) or silence (3 s or more) |
| `WARN: flash 3:41.2 shot 0.10s (#19 ...)` | A shot shorter than 0.25 s between two cuts or clip joins |
| `WARN: loudness -33.1 LUFS outside -30…-9` / `WARN: true peak -0.2 dBTP above -1.0` | Whole-output loudness or peak out of range |
| `WARN: QA scan failed: ...` | The scan itself could not run; the other checks still stand |

## 2. Report

Report from the `verify.py` output only: output path, duration and size as printed, the frame
and LUT clip count from `config.json` / `clips.json`, and the result with every `PROBLEM:` line
verbatim. In draft mode (including a pilot render) the frame is the 720 px draft frame. Do not rely on hook output: it may
not have reached you.

## 3. Spot-check

The checks cannot see content. Ask one numbered message, naming real clips from `clips.json`:

```
Please watch a few points and answer 1.X 2.Y 3.Z:
1. Is every moment you most wanted there? Must-finds are at #4 (m1, 1:12), #19 (m2, 4:05).
2. Do the LUT clips (#3-#11, 22.08) look natural next to the others?
3. Any clip to trim, drop, relabel or add? Sound OK all the way through?
```

Times are cumulative from `clips.json` durations; for a pilot render, count from the first clip
of the rendered range (it plays at 0:00) and name only clips inside that range.

Warnings are not defects by themselves (a fade through black or a still title can be on purpose).
After the question list, add one numbered item per `WARN:` line, naming its clip and time, and ask
whether it is a defect: `4. WARN black 3:41.2–3:42.0 in #19 (22.08/DJI_0031_D.MP4 @ 34.2s): defect or intended?`
A warning the user calls a defect goes to step 4 like any other fix.

## 4. Fixes

When the user's notes carry output timestamps (`3:41`, `1:02:03`, `12.5`), map them all in one call:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify.py" "<project>" [--draft] --locate 3:41 12:40
```

Each line is `3:41 → #19 22.08/DJI_0031_D.MP4 @ 34.2s (clip 30.0→38.0, 0:04 into it) "Night Market"`
(clip number in `clips.json`, source file, source time). Times past the end or not parseable print
`past the end (M:SS)` / `ERROR: not a time` and exit 1; the rest are still answered. Pass
`video-summary:plan` concrete edits built from these lines (`#19 start 34.2`), not the raw timestamps.

Every change to the cut goes back to `video-summary:plan` (edit the table, rewrite `clips.json`),
LUT changes to `video-summary:grade`, then a new render (`/video-summary:render <project>`).
After the fixes are collected, ask once whether any of them should become a lasting rule for
future videos (`Make "no clip under 3 s" a saved preference? 1.yes / 2.no / 3.reword`).
Propose the exact wording, one line, general (no file names or timestamps). Only after the user
approves that wording, run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/prefs.py" add "<approved wording>" --project "<project name>"
```

Never add a rule silently or reworded. `prefs.py show` lists the rules, `prefs.py remove N`
drops one.

Never re-run analysis for a fix unless the user reports a moment that is missing from the
shortlist itself: then `video-summary:plan` re-scans those clips.

## 5. Clean up

Work is done when the user accepts the final (non-draft) render. Then run, without asking again:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/project.py" clean "<project>"
```

Report its line and say that the cache was removed except the render manifest, so verify and
`verify.py --locate` keep working on the accepted video. Re-planning later needs analyze again:
transcripts come back with `speech.py transcribe`, and thumbnails are not regenerated for existing
candidates, so re-run `sample.py --overwrite` (it clears cached scores and resets moments.json: scores, groups and must_find, so all scoring is redone). Accepting a draft or a pilot render never cleans: the cache is still needed for the final.

## Validate → fix → re-run

1. `verify.py` exits 0.
2. The user's spot-check answers have no open item.

On a failed check, find the cause in the table above, fix it in the stage that owns it, render
again and re-run `verify.py`. Report a check that still fails with its exact line; never call
the video verified while either step is open.
