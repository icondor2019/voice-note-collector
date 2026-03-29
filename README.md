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
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload

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
