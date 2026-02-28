# soulmane

Discord + slskd automation bot for reliable Soulseek downloads.

## One-liner onboarding (run as `gary`)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/slimelab-ai/soulmane/master/scripts/onboard.sh)
```

This prompts for:
- Discord token
- bot name
- Soulseek creds (reuse/generate)
- slskd URL + web auth
- local OpenAI-compatible endpoint + model id

It writes:
- `~/.config/soulseek-credentials.env` (if generated)
- `~/.local/share/soulmane/.env`

## Install + run

```bash
cd ~/.local/share/soulmane
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

## Commands

- `/download <query>`
  - Runs slskd batch strategy: enqueue multiple peers, pick first healthy transfer, cancel the rest.
  - Does **not** claim success without transfer evidence.
- `/status [job_id]`
  - Shows latest job (or specific job) state + transfer bytes/states.
- `/cancel <job_id>`
  - Cancels all tracked transfer IDs for that job.

## Mention replies (personality mode)

If you @mention the bot in chat, it replies using your local OpenAI-compatible LLM (`OPENAI_BASE_URL`, `OPENAI_MODEL`) with the configured `PERSONA_PROMPT`.

**Important:** enable **Message Content Intent** for the Discord application, or mention replies won’t trigger.

## Behavior guarantees

- No fake "done" reports: job success is based on transfer state/bytes in slskd.
- Duplicate control: once a winner starts (bytes threshold), the bot cancels other peers in that batch.
- Audit trail: jobs + transfer IDs are stored in `jobs.db`.

## Systemd user service (optional)

```bash
mkdir -p ~/.config/systemd/user
cp systemd/soulmane.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now soulmane
systemctl --user status soulmane
```

## Environment

See `.env.example` for all variables.
