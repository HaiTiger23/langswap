#!/bin/zsh
set -e
cd "${0:A:h}"
export GRADIO_ANALYTICS_ENABLED=False
export PYTORCH_ENABLE_MPS_FALLBACK=1
export HF_HUB_DISABLE_XET=1
export HF_HUB_DISABLE_TELEMETRY=1
export PATH="/Users/macbook/Project/voice-text-studio/resources/ffmpeg/darwin-arm64:$PATH"
exec .venv/bin/python -u studio_server.py
