#!/usr/bin/env bash
set -euo pipefail
export PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"
mkdir -p lisbon/15.06
ffmpeg -hide_banner -v error -y -f lavfi -i "testsrc2=size=320x240:rate=25:duration=2" -c:v libx264 -pix_fmt yuv420p lisbon/15.06/DJI_0001_D.MP4
