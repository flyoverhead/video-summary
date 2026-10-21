#!/usr/bin/env bash
set -euo pipefail
export PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"
mkdir -p 22.08
ffmpeg -hide_banner -v error -y -f lavfi -i "testsrc2=size=320x240:rate=25:duration=3" -f lavfi -i "sine=frequency=440:duration=3" -ac 2 -c:v libx264 -pix_fmt yuv420p -c:a aac 22.08/DJI_0001_D.MP4
mkdir -p thumbs
ffmpeg -hide_banner -v error -y -f lavfi -i "color=c=0x808080:size=320x240,format=gray,format=yuv420p" -frames:v 1 thumbs/c0001.jpg
