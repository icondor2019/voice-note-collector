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
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload

## Test
pytest -v
