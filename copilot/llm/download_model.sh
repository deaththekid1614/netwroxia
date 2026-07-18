#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# NETWROXIA — Download Mistral 7B Instruct Q4_K_M
# Source: TheBloke @ HuggingFace (quantized for CPU inference)
# Size: ~4.4GB | RAM at runtime: ~5GB peak, ~3GB steady
# ═══════════════════════════════════════════════════════════════════════════════

set -e  # Exit on any error

MODEL_DIR="$HOME/IDE/netwroxia/copilot/llm"
MODEL_FILE="mistral-7b-instruct-v0.2.Q4_K_M.gguf"
MODEL_URL="https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/${MODEL_FILE}"

echo "══════════════════════════════════════════════════════════════════"
echo "  NETWROXIA — Downloading Mistral 7B Q4_K_M"
echo "  Target: ${MODEL_DIR}/${MODEL_FILE}"
echo "  Size: ~4.4 GB"
echo "  Time: 10-30 min depending on connection"
echo "══════════════════════════════════════════════════════════════════"

mkdir -p "$MODEL_DIR"
cd "$MODEL_DIR"

# Check if already downloaded
if [ -f "$MODEL_FILE" ]; then
    echo "✅ Model already exists: ${MODEL_FILE}"
    ls -lh "$MODEL_FILE"
    echo ""
    echo "To re-download, delete the file first:"
    echo "  rm ${MODEL_DIR}/${MODEL_FILE}"
    exit 0
fi

# Download with resume support
echo "⬇️  Starting download (resumable)..."
wget --continue --show-progress "$MODEL_URL" -O "$MODEL_FILE"

echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  ✅ Download complete!"
echo "  Location: ${MODEL_DIR}/${MODEL_FILE}"
echo "══════════════════════════════════════════════════════════════════"
ls -lh "$MODEL_FILE"
