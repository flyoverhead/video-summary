# DJI footage: known issues

Ported from the old `tools/WORKFLOW.md`. Most are already handled by the bundled scripts; this
file says what the symptom looks like and where the fix lives, so nobody undoes it.

## Contents

- [No audio in middle clips](#no-audio-in-middle-clips)
- [Noisy or broken audio after concat](#noisy-or-broken-audio-after-concat)
- [drawtext filter not found](#drawtext-filter-not-found)
- [D-LogM looks like Rec.709 in the tags](#d-logm-looks-like-rec709-in-the-tags)
- [Frame rate differs per clip](#frame-rate-differs-per-clip)
- [Mixed shapes in one folder](#mixed-shapes-in-one-folder)
- [Render is slow](#render-is-slow)
- [LRF proxies and AppleDouble files](#lrf-proxies-and-appledouble-files)

## No audio in middle clips

**Cause:** DJI clips alternate between mono and stereo. `ffmpeg concat -c copy` silently drops
audio when channel counts differ between clips.
**Handled:** `render_summary.py` encodes every intermediate clip as mono from the left channel
(`pan=mono|c0=c0`, `-ac 1`) and upmixes to stereo (`-ac 2`) at concat. Clips without audio get
silent mono. Keep this; `verify.py` fails an output that is not 2-channel.

## Noisy or broken audio after concat

**Cause:** the right channel of DJI stereo clips is noisy, and mixed layouts corrupt the concat
transitions.
**Handled:** the same left-channel normalisation. If an old intermediate set is reused, check the
channel count of each intermediate in `<config.tmp>/final/clip_NNN.mp4` (or `draft/`); every one
must be 1 channel. Re-render rather than patching intermediates: `render_summary.py` rebuilds all
of them.

## drawtext filter not found

**Cause:** the plain `ffmpeg` Homebrew formula has no freetype, so `drawtext` is missing.
**Fix (user runs):**

```bash
brew unlink ffmpeg
brew install ffmpeg-full
```

The scripts already prefix `PATH` with `/opt/homebrew/opt/ffmpeg-full/bin`
(`common.ffmpeg_env()`); a bare `ffmpeg` call outside them may still pick the wrong binary.

## D-LogM looks like Rec.709 in the tags

**Cause:** Osmo Action 6 D-LogM clips report `bt709` colour tags, so container metadata cannot
tell log from normal footage.
**Not detectable:** calibration on 2026-10-20 (40 raw Osmo Action 6 clips from four trips, all
D-LogM, against the same thumbnails passed through the bundled LUT) found no frame statistic that
separates them at clip level: saturation, luma percentiles and luma range overlap across scenes
(an indoor squash court in D-LogM is brighter and flatter-looking than an outdoor street after
the LUT). The `djmd` track has no field known to encode the profile: all calibrated clips were
D-LogM, so nothing could be compared. **Handled:** `lut.py detect` reports every clip as
`unknown` with its camera source (`dji` = has `djmd`), and `video-summary:grade` always shows a
before/after preview and records only the user's answer.

## Frame rate differs per clip

**Cause:** 25, 29.97 and 50 fps have all been seen in one trip.
**Handled:** `probe.py` reads fps per clip; the output fps is the majority source fps and
`render_summary.py` resamples the rest. Never assume 50.

## Mixed shapes in one folder

**Cause:** square (3840×3840) is usual, but some clips are wide or vertical.
**Handled:** the output frame is the majority shape; odd clips are fitted with a blurred-fill
background, never cropped. `project.py summary` lists them on the `Fitted` line.

## Render is slow

**Cause:** 4K HEVC 10-bit decode. `hevc_videotoolbox` runs at about 0.25× realtime, so a
10-minute output takes about 40 minutes.
**Mitigation:** run a `--draft` render first (720 px long side, 8-bit, quality 35) to review the
cut, and run every render in the background.

## LRF proxies and AppleDouble files

**Cause:** DJI writes `.LRF` low-res proxies next to each `.MP4`; copying from exFAT cards leaves
`._*` AppleDouble files.
**Handled:** `probe.py` takes only `*.MP4` / `*.mp4`, skips dotfiles and any
`SUMMARY_VIDEO*.mp4`. Never delete or move these files; they belong to the source folder.
