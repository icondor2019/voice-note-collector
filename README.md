# continues_note_taker
The objetive of this app is to save voice note from telegram, organize them by topics, and serve as structured inputs for studing or working porpuses

## Stack
- FastAPI
- Supabase
- Telegram Bot
- Groq (Whisper)

## Docs
Ver `docs/project_spec.md`

## Run

### Prerequisites
- [Infisical CLI](https://infisical.com/docs/cli/overview) installed and authenticated
- Project secrets stored in Infisical under the `dev` environment

### Setup
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Local execution (with Infisical)
Secrets are managed via [Infisical](https://infisical.com). No `.env` file is needed.

```bash
make run_app
```

This runs:
```bash
infisical run --env=dev -- uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Infisical injects all required environment variables at startup. See `.env.example` for the full list of expected variables.

## Telegram webhook setup (local)
1. Configure environment variables:
   - TELEGRAM_BOT_TOKEN
   - TELEGRAM_BOT_USER
2. Expose your local server (for example, using a tunnel like ngrok) and copy the HTTPS URL.
3. Configure the webhook with Telegram:
   ```bash
   curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
     -H "Content-Type: application/json" \
     -d '{"url": "https://your-tunnel-url/api/telegram/webhook"}'
   ```
4. Send a text or voice message to the bot and inspect `./data/telegram_ingestion_events.jsonl`.

## Replay test from fixture
```bash
curl -X POST "http://localhost:8000/api/telegram/webhook" \
  -H "Content-Type: application/json" \
  --data-binary @tests/fixtures/telegram/text_message.json
```

Replay the voice fixture (first request stored, second request deduped):
```bash
curl -X POST "http://localhost:8000/api/telegram/webhook" \
  -H "Content-Type: application/json" \
  --data-binary @tests/fixtures/telegram/voice_message.json
curl -X POST "http://localhost:8000/api/telegram/webhook" \
  -H "Content-Type: application/json" \
  --data-binary @tests/fixtures/telegram/voice_message.json
```

Expected outcome:
- First response: `{"status":"ok","outcome":"stored",...}`
- Second response: `{"status":"ok","outcome":"duplicate",...}`

## Test
./venv/bin/pytest -v
