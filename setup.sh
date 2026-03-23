#!/data/data/com.termux/files/usr/bin/bash
# =============================================================
# Termux AI Coding Assistant — Automated Setup Script
# =============================================================
# Run this once in Termux to set everything up:
#   bash setup.sh
# =============================================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

print_step() { echo -e "\n${CYAN}▶ $1${NC}"; }
print_ok()   { echo -e "${GREEN}✓ $1${NC}"; }
print_warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
print_err()  { echo -e "${RED}✗ $1${NC}"; }

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════╗"
echo "  ║   Termux AI Coding Assistant Setup   ║"
echo "  ╚══════════════════════════════════════╝"
echo -e "${NC}"

# ── Step 1: Update packages ───────────────────────────────────
print_step "Updating Termux packages…"
pkg update -y && pkg upgrade -y
print_ok "Packages updated"

# ── Step 2: Install system dependencies ───────────────────────
print_step "Installing system dependencies…"
pkg install -y python python-pip git tmux curl libxml2 libxslt ca-certificates
print_ok "System dependencies installed"

# ── Step 3: Install Python packages ───────────────────────────
print_step "Installing Python dependencies…"
pip install --upgrade pip
pip install -r requirements.txt
print_ok "Python dependencies installed"

# ── Step 4: Create workspace directory ────────────────────────
print_step "Creating workspace directory…"
mkdir -p ~/ai-workspace
mkdir -p logs
print_ok "Workspace ready at ~/ai-workspace"

# ── Step 5: Configure .env ────────────────────────────────────
print_step "Configuring environment…"

if [ -f ".env" ]; then
    print_warn ".env already exists — skipping creation"
else
    cp .env.example .env
    print_ok ".env created from template"
    print_warn "You must edit .env with your API keys before running the bot!"
    echo ""
    echo -e "  Run: ${YELLOW}nano .env${NC}"
    echo ""
fi

# ── Step 6: Create tmux startup script ────────────────────────
print_step "Creating bot startup script…"

cat > start_bot.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Start the AI bot in a tmux session
SESSION="ai-bot"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Bot session already running. Attaching…"
    tmux attach -t "$SESSION"
else
    echo "Starting bot in tmux session: $SESSION"
    cd "$(dirname "$0")"
    tmux new-session -d -s "$SESSION" "python main.py; bash"
    echo "Bot started! Attaching to session…"
    tmux attach -t "$SESSION"
fi
EOF

chmod +x start_bot.sh
print_ok "start_bot.sh created"

# ── Step 7: Create stop script ────────────────────────────────
cat > stop_bot.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
SESSION="ai-bot"
if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux kill-session -t "$SESSION"
    echo "Bot session stopped."
else
    echo "No active bot session found."
fi
EOF

chmod +x stop_bot.sh
print_ok "stop_bot.sh created"

# ── Final instructions ────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║            Setup Complete! ✓                 ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo "Next steps:"
echo ""
echo "  1. Edit your config:"
echo -e "     ${YELLOW}nano .env${NC}"
echo ""
echo "  2. Start the bot:"
echo -e "     ${YELLOW}bash start_bot.sh${NC}"
echo ""
echo "  3. Stop the bot:"
echo -e "     ${YELLOW}bash stop_bot.sh${NC}"
echo ""
echo "  4. View logs:"
echo -e "     ${YELLOW}tail -f logs/bot.log${NC}"
echo ""
echo -e "${CYAN}Tip: Disable battery optimization for Termux in Android settings${NC}"
echo -e "${CYAN}     to prevent the bot from being killed when your phone sleeps.${NC}"
echo ""
