#!/usr/bin/env bash
# ==============================================================================
# install.sh — Bootstrap Herdr Multi-Agent Dev Squad
# ==============================================================================
set -e

DEV_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"

echo "=================================================="
echo "🚀 Installing Herdr Multi-Agent Dev Squad"
echo "   Workspace: ${DEV_ROOT}"
echo "=================================================="

# 1. Check prerequisites
missing=()
for cmd in python3 herdr uv; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        missing+=("$cmd")
    fi
done

if [ ${#missing[@]} -gt 0 ]; then
    echo "[!] Missing required tools: ${missing[*]}"
    echo "    Please install them before launching the squad."
else
    echo "[✓] Core prerequisites found: python3, herdr, uv"
fi

# 2. Check optional agent CLIs
found_clis=()
for cli in agy pi claude opencode codex; do
    if command -v "$cli" >/dev/null 2>&1; then
        found_clis+=("$cli")
    fi
done
if [ ${#found_clis[@]} -gt 0 ]; then
    echo "[✓] Detected agent CLIs: ${found_clis[*]}"
else
    echo "[!] No agent CLIs detected (agy, pi, claude, opencode, codex)."
    echo "    Install at least one CLI and configure .team/agents.json."
fi

# 3. Link 'dev' CLI into ~/.local/bin
mkdir -p "$BIN_DIR"
chmod +x "${DEV_ROOT}/dev" "${DEV_ROOT}/.team/scripts/"*.sh "${DEV_ROOT}/.team/scripts/team_hub.py"
ln -sf "${DEV_ROOT}/dev" "${BIN_DIR}/dev"
echo "[✓] Linked CLI: ${BIN_DIR}/dev -> ${DEV_ROOT}/dev"

# 4. Initialize local agent config if not present
if [ ! -f "${DEV_ROOT}/.team/agents.json" ] && [ -f "${DEV_ROOT}/.team/agents.example.json" ]; then
    cp "${DEV_ROOT}/.team/agents.example.json" "${DEV_ROOT}/.team/agents.json"
    echo "[✓] Created .team/agents.json from agents.example.json (customize CLIs/models here)"
fi

echo ""
echo "=================================================="
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. (Optional) Edit .team/agents.json to choose your preferred CLIs/models"
echo "  2. Bind your first project:"
echo "       dev switch ~/Work/my-project"
echo "  3. Launch the 8-agent squad & attach:"
echo "       dev up && dev start"
echo "  4. Launch the Web Command Deck (http://localhost:8080):"
echo "       dev web"
echo "=================================================="
