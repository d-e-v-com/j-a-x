#!/usr/bin/env bash
# JAX Install Script
# Checks prerequisites and sets up the JAX agent environment.

set -euo pipefail

echo "=== JAX Installer ==="
echo ""

# Check Python 3.10+
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+ first."
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Python: $PY_VERSION"

# Check Ollama
if ! command -v ollama &>/dev/null; then
    echo "WARNING: ollama not found in PATH."
    echo "  Install from: https://ollama.ai"
    echo "  Or set OLLAMA_BASE_URL to point to a remote Ollama instance."
else
    echo "Ollama: $(ollama --version 2>/dev/null || echo 'installed')"
fi

# Check if Ollama is reachable
OLLAMA_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
if curl -s --connect-timeout 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    echo "Ollama API: reachable at $OLLAMA_URL"
    MODELS=$(curl -s "$OLLAMA_URL/api/tags" | python3 -c "import sys,json; d=json.load(sys.stdin); [print(f'  - {m[\"name\"]}') for m in d.get('models',[])]" 2>/dev/null || echo "  (could not list models)")
    echo "Available models:"
    echo "$MODELS"
else
    echo "WARNING: Ollama API not reachable at $OLLAMA_URL"
    echo "  Start Ollama: ollama serve"
    echo "  Or set OLLAMA_BASE_URL environment variable"
fi

# Check ripgrep (optional but recommended)
if command -v rg &>/dev/null; then
    echo "ripgrep: $(rg --version | head -1)"
else
    echo "WARNING: ripgrep (rg) not found. grep_search tool will fall back to grep."
    echo "  Install: sudo apt install ripgrep  OR  brew install ripgrep"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Quick start:"
echo "  # Headless mode:"
echo "  python3 src/jax_headless.py --repo . --role sysadmin --model qwen3-coder --prompt \"Your task\""
echo ""
echo "  # Interactive chat:"
echo "  python3 src/jax_chat.py --role sysadmin"
