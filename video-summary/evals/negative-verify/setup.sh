#!/usr/bin/env bash
set -euo pipefail
export PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"
printf "data\n" > backup.tar.gz
shasum -a 256 backup.tar.gz > SHA256SUMS
