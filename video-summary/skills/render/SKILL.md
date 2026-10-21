---
name: render
description: Renders a video-summary project — shows the pre-render summary (type, clips, duration, frame, LUT clips, music, quality, output, estimated time), offers a fast low-res draft first, then runs the final hevc_videotoolbox render in the background and hands off to verification. Use when clips.json and config.json are confirmed and the user wants a draft or the final video. Not for checking an existing output — use video-summary:verify.
argument-hint: "[project-folder] [draft|final]"
disable-model-invocation: true
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/*) Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/*) Bash(date +%s) Read Glob Skill
---

# Render

Request: $ARGUMENTS

Renders read the source clips and write only `SUMMARY_VIDEO.mp4` or `SUMMARY_VIDEO.draft.mp4`
into the project folder; intermediates go to `config.json` `tmp` in the cache. The pre-render
hook validates `config.json`, `clips.json` and `probe.json` and blocks the command on a problem;
the result of a render comes from `verify.py` (step 5), never from hook output: a background
run's hook output may not reach you. Quote every path.

## Checklist

Copy and track:

```
- [ ] 1. Preconditions and pre-render summary (project.py summary)
- [ ] 2. Confirm with the user; offer a draft first
- [ ] 3. Draft (optional): background run, measure speed, user reviews
- [ ] 4. Final: existing-output guard, background run
- [ ] 5. Report; video-summary:verify
```

## 1. Pre-render summary

`config.json`, `clips.json`, `probe.json` and `brief.json` must exist; if not, the plan is not
done: use `video-summary:plan`.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/project.py" summary "<project>"
```

```
Type:      trip
Clips:     74 clips
Duration:  12m 40s (target 10-15 min)
Frame:     square 2560x2560 @ 50 fps
LUT:       9 of 74 (22.08/DJI_0001_D.MP4, ...)
Fitted:    2 clips with blurred fill (25.08/DJI_0107_D.MP4 wide, ...)
Music:     none
Quality:   standard (60)
Output:    /Users/me/Movies/camera/squash/SUMMARY_VIDEO.mp4
Estimate:  ~50m 40s final at 0.25x realtime
```

Show it as is. The final estimate is 0.25× realtime (4K HEVC decode is the bottleneck). The
draft speed is unknown until the first draft; after one, use the measured speed. `Fitted` clips
are scaled into the frame over a blurred copy of themselves, never cropped: say so.

## 2. Confirm

One numbered message:

```
1. Render a draft first (720 px, fast, replaces any previous SUMMARY_VIDEO.draft.mp4), go
   straight to the final, or change something first?
```

Changes go back to `video-summary:plan` (cut, labels, music, quality) or `video-summary:grade`
(LUT). Never start a final render without a yes to the summary above.

## 3. Draft

The draft is disposable and is overwritten without asking; tell the user that once.

```bash
date +%s
```

Then, with the Bash tool's `run_in_background`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/render_summary.py" "<project>" --draft
```

Progress lines are `[12/74] file [start→end] "label"`; the last line is
`Done!  <project>/SUMMARY_VIDEO.draft.mp4`. When it exits, run `date +%s` again. Measured draft
speed = planned duration ÷ elapsed seconds; report it (`draft took 6m 10s, 2.1x realtime`).
Run `video-summary:verify` in draft mode, then ask the user to watch the draft: any change goes
to `video-summary:plan`, and the draft is re-rendered on request.

## 4. Final

If `Output` says `exists`, show the existing file's size from the summary and ask in one numbered
question whether to replace it; only on a yes add `--overwrite`. Without it the script refuses
(`exists, use --overwrite`).

With `run_in_background`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/render_summary.py" "<project>"
```

Tell the user the estimate and that they can keep working; you are notified when it exits. Do
not poll. A render error is printed as `ERROR: clip 12 (22.08/DJI_0031_D.MP4) failed: ...` with
the ffmpeg tail; see [references/dji-known-issues.md](references/dji-known-issues.md) before
changing anything.

## 5. Report

Invoke `video-summary:verify` with the project folder (`--draft` for a draft). Its `verify.py`
prints `Output:`, `Duration:`, `Size:` and `OK` or `PROBLEM:` lines; report those verbatim. If a
`Post-render check (verify.py):` note was added to your context, it is the same output and does
not replace the verify run. Verify then asks the user to spot-check.

## Validate → fix → re-run

1. The render exits 0 and prints `Done!  <path>`.
2. `video-summary:verify` reports `OK`.

If the pre-render hook blocks (`Pre-render check failed:` with a list) or the script refuses
(`ERROR: refusing to render:` with the same list), fix each item in
`video-summary:plan` (a clip past its source end, a missing file) and re-run the same render
command. If ffmpeg fails, read the error, check the known issues, fix the cause, and re-run;
intermediates are rebuilt each run, so a re-run is always safe. Never delete or move source
clips to get a render through.
