# video-summary

Claude Code plugin that turns raw camera footage into a short summary video. Python standard library helpers plus ffmpeg.

Status: work in progress (v0.2.0: speech, cut on pause, contact sheet, pilot render, output QA, preferences).

## Requirements

- Python 3.11+
- ffmpeg-full at `/opt/homebrew/opt/ffmpeg-full/bin` (libx265, libass)
- whisper-cpp (`whisper-cli`) and the model `~/.cache/whisper.cpp/ggml-large-v3-turbo.bin`; analysis stops with these commands when either is missing:

```bash
brew install whisper-cpp
mkdir -p ~/.cache/whisper.cpp && curl -L -o ~/.cache/whisper.cpp/ggml-large-v3-turbo.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin
```

Overrides: `VIDEO_SUMMARY_WHISPER_BIN`, `VIDEO_SUMMARY_WHISPER_MODEL`.

## Cache

Transcripts, thumbnails and scores live in `~/.cache/video-summary/<project>`; `project.py clean "<project>"` removes that folder except the render manifest (verify and `--locate` keep working), and verify runs it once you accept the final render.

## Development

```bash
python3 -m pytest -v
```
