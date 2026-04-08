# bash:install.sh
#!/usr/bin/env bash
set -e

CYAN='\033[0;36m'; GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${CYAN}claude-check-repo installer${NC}\n"

if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Error: python3 not found${NC}"; exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo $PY_VERSION | cut -d. -f1)
PY_MINOR=$(echo $PY_VERSION | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]); then
    echo -e "${RED}Error: Python 3.11+ required (found $PY_VERSION)${NC}"; exit 1
fi
echo -e "  ${GREEN}✓${NC} Python $PY_VERSION"

if ! command -v git &>/dev/null; then
    echo -e "${RED}Error: git not found.${NC}"; exit 1
fi
echo -e "  ${GREEN}✓${NC} git $(git --version | cut -d' ' -f3)"

echo -e "\n  Installing claude-check-repo..."
pip install -e . --quiet

command -v claude-check-repo &>/dev/null \
    && echo -e "  ${GREEN}✓${NC} claude-check-repo installed" \
    || echo -e "  ${YELLOW}⚠${NC} CLI not in PATH. Run: pip install -e ."

echo -e "\n  Optional tools:"
command -v ruff &>/dev/null \
    && echo -e "  ${GREEN}✓${NC} ruff (linting)" \
    || echo -e "  ${YELLOW}○${NC} ruff not found  →  pip install ruff"

python3 -c "import pytest" 2>/dev/null \
    && echo -e "  ${GREEN}✓${NC} pytest (testing)" \
    || echo -e "  ${YELLOW}○${NC} pytest not found →  pip install pytest pytest-cov"

echo -e "\n  Claude CLI:"
if command -v claude &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} claude found: $(claude --version 2>/dev/null || echo 'installed')"
else
    echo -e "  ${YELLOW}⚠${NC} claude CLI not found"
    echo -e "     Install Claude Code: https://claude.ai/code"
    echo -e "     No API key required — uses your Claude subscription (OAuth)"
fi

echo -e "\n${GREEN}Done!${NC}"
echo -e "\nUsage:"
echo -e "  claude-check-repo                   # analyze current directory"
echo -e "  claude-check-repo ./path/to/repo    # analyze specific repo"
echo -e "  claude-check-repo --help            # all options"