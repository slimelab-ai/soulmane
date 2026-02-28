# soulmane

Discord + slskd automation bot for reliable Soulseek downloads.

## Planned commands
- `/download <query>`: batch enqueue multiple peers, pick first healthy transfer, cancel duplicates
- `/status [query]`: show active job and transfer progress
- `/cancel <job_id>`: cancel queued/in-progress transfers for a job

## One-liner onboarding (run as `gary`)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/slimelab-ai/soulmane/master/scripts/onboard.sh)
```

This will prompt for:
- Discord token
- Bot name
- Soulseek creds (reuse existing or generate new)
- slskd URL + web auth
- local OpenAI-compatible model endpoint + model id

Then it writes:
- `~/.config/soulseek-credentials.env` (if generated)
- `~/.local/share/soulmane/.env`

## Status
Repo initialized in `slimelab-ai/soulmane`.
MVP scaffolding in progress.
