---
name: verify
description: Verifies a rendered video-summary output against its plan — duration vs clips.json, stereo audio, frame size and per-clip LUT flags from the render manifest via verify.py — reports the result, asks the user to spot-check and routes any fix back to planning. Use after a draft or final render, or when the user asks whether a summary video came out right. Not for changing the cut — use video-summary:plan.
argument-hint: "[project-folder] [--draft]"
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/*) Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/*) Read Glob
---

# Verify the output

Project folder: $ARGUMENTS

Read-only: this skill inspects the output and the plan files and changes nothing. Quote every
path.

## Checklist

Copy and track:

```
- [ ] 1. verify.py (add --draft for the draft)
- [ ] 2. Report
- [ ] 3. Spot-check question
- [ ] 4. Fixes go to video-summary:plan, then a new render
```

## 1. Run the checks

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify.py" "<project>"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify.py" "<project>" --draft
```

It prints the facts, then `OK` (exit 0) or one `PROBLEM:` line per problem (exit 1):

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

## 2. Report

Report from the `verify.py` output only: output path, duration and size as printed, the frame
and LUT clip count from `config.json` / `clips.json`, and the result with every `PROBLEM:` line
verbatim. In draft mode the frame is the 720 px draft frame. Do not rely on hook output: it may
not have reached you.

## 3. Spot-check

The checks cannot see content. Ask one numbered message, naming real clips from `clips.json`:

```
Please watch a few points and answer 1.X 2.Y 3.Z:
1. Is every moment you most wanted there? Must-finds are at #4 (m1, 1:12), #19 (m2, 4:05).
2. Do the LUT clips (#3-#11, 22.08) look natural next to the others?
3. Any clip to trim, drop, relabel or add? Sound OK all the way through?
```

Times are cumulative from `clips.json` durations.

## 4. Fixes

Every change to the cut goes back to `video-summary:plan` (edit the table, rewrite `clips.json`),
LUT changes to `video-summary:grade`, then a new render (`/video-summary:render <project>`).
Never re-run analysis for a fix unless the user reports a moment that is missing from the
shortlist itself: then `video-summary:plan` re-scans those clips.

## Validate → fix → re-run

1. `verify.py` exits 0.
2. The user's spot-check answers have no open item.

On a failed check, find the cause in the table above, fix it in the stage that owns it, render
again and re-run `verify.py`. Report a check that still fails with its exact line; never call
the video verified while either step is open.
