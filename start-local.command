#!/bin/zsh
set -e
cd "${0:A:h}"
export GRADIO_ANALYTICS_ENABLED=False
export PATH="/Users/macbook/Project/voice-text-studio/resources/ffmpeg/darwin-arm64:$PATH"
exec ./start-dub.command
