#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/.local/share/soulmane}"
MODEL_BASE_DEFAULT="http://127.0.0.1:8013/v1"
SLSKD_BASE_DEFAULT="http://127.0.0.1:5030"

mkdir -p "$APP_DIR" "$HOME/.config"
cd "$APP_DIR"

if [[ ! -d .git ]]; then
  git clone https://github.com/slimelab-ai/soulmane.git .
fi

printf "\n== Soulmane onboarding ==\n"
read -rp "Discord bot token: " DISCORD_TOKEN
read -rp "Bot display name [soulmane]: " BOT_NAME
BOT_NAME="${BOT_NAME:-soulmane}"

read -rp "Use existing Soulseek creds file (~/.config/soulseek-credentials.env)? [Y/n]: " USE_EXISTING
USE_EXISTING="${USE_EXISTING:-Y}"

if [[ "$USE_EXISTING" =~ ^[Nn]$ ]]; then
  read -rp "Soulseek username (blank to auto-generate): " SLSK_USER
  if [[ -z "${SLSK_USER}" ]]; then
    SLSK_USER="${USER}_$(date +%s)_$RANDOM"
  fi
  read -rsp "Soulseek password (blank to auto-generate): " SLSK_PASS; echo
  if [[ -z "${SLSK_PASS}" ]]; then
    SLSK_PASS="$(python3 - <<'PY'
import secrets,string
alphabet=string.ascii_letters+string.digits
print(''.join(secrets.choice(alphabet) for _ in range(24)))
PY
)"
  fi
  cat > "$HOME/.config/soulseek-credentials.env" <<EOF
SOULSEEK_ACCOUNT=$SLSK_USER
SOULSEEK_PASSWORD=$SLSK_PASS
EOF
  chmod 600 "$HOME/.config/soulseek-credentials.env"
  echo "Wrote $HOME/.config/soulseek-credentials.env"
fi

# pull creds (existing or newly created)
if [[ -f "$HOME/.config/soulseek-credentials.env" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$HOME/.config/soulseek-credentials.env"; set +a
else
  echo "ERROR: missing $HOME/.config/soulseek-credentials.env"
  exit 1
fi

read -rp "slskd API base URL [$SLSKD_BASE_DEFAULT]: " SLSKD_BASE_URL
SLSKD_BASE_URL="${SLSKD_BASE_URL:-$SLSKD_BASE_DEFAULT}"
read -rp "slskd web username [gary]: " SLSKD_WEB_USERNAME
SLSKD_WEB_USERNAME="${SLSKD_WEB_USERNAME:-gary}"
read -rsp "slskd web password (blank => Soulseek password): " SLSKD_WEB_PASSWORD; echo
SLSKD_WEB_PASSWORD="${SLSKD_WEB_PASSWORD:-$SOULSEEK_PASSWORD}"

read -rp "Local OpenAI-compatible model base URL [$MODEL_BASE_DEFAULT]: " MODEL_BASE_URL
MODEL_BASE_URL="${MODEL_BASE_URL:-$MODEL_BASE_DEFAULT}"
read -rp "Model id [huihui-qwen3.5-35b-a3b-Q4_K_M.v2.gguf]: " MODEL_ID
MODEL_ID="${MODEL_ID:-huihui-qwen3.5-35b-a3b-Q4_K_M.v2.gguf}"

cat > .env <<EOF
# Discord
DISCORD_TOKEN=$DISCORD_TOKEN
BOT_NAME=$BOT_NAME

# slskd
SLSKD_BASE_URL=$SLSKD_BASE_URL
SLSKD_WEB_USERNAME=$SLSKD_WEB_USERNAME
SLSKD_WEB_PASSWORD=$SLSKD_WEB_PASSWORD

# Soulseek account (for docs / optional direct client flows)
SOULSEEK_ACCOUNT=$SOULSEEK_ACCOUNT
SOULSEEK_PASSWORD=$SOULSEEK_PASSWORD

# Local OpenAI-compatible LLM provider
OPENAI_BASE_URL=$MODEL_BASE_URL
OPENAI_API_KEY=local-dev
OPENAI_MODEL=$MODEL_ID
EOF
chmod 600 .env

echo "\nWrote $APP_DIR/.env"
echo "\nNext:"
echo "  cd $APP_DIR"
echo "  # when app is implemented: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && python bot.py"
