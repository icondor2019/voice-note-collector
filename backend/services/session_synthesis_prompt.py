from __future__ import annotations

import json

SYNTHESIS_PROMPT = """You are a session synthesis assistant. You will receive a list of voice note transcriptions from one reading/learning session. Your task is to synthesize them into ONE coherent markdown document.

CRITICAL: Distill and include ALL relevant information from the notes. Do not be vague. Be specific and complete. The document must capture everything worth remembering — not a vague overview, but a thorough, specific synthesis.

Preserve the user's own reflections, thoughts, and ideas — not just a summary of the source material. If the user expressed opinions, questions, or personal insights, include them verbatim or closely paraphrased.

Produce a JSON object with two fields:
- "title": A concise, descriptive title for the session (1 sentence)
- "content": A full markdown document following the skeleton below

The content MUST follow this exact skeleton:

```
# {title}

## Summary
{2-3 paragraphs preserving the user's own reflections, not just a summary of the source. Complete and specific, not vague.}

## Key Ideas
{3-7 bullet points distilling ALL relevant information from the notes. Use "- " prefix for each bullet. Be specific and complete.}

## Open Questions
_(To be explored during Socratic review.)_

## Knowledge Gaps
_(To be identified during reflection.)_

## Reflections
_(To be added during review.)_

## Mind Changes
_(To be recorded when understanding shifts.)_
```

IMPORTANT:
- Fill Summary with 2-3 complete, specific paragraphs. Preserve the user's own voice and reflections.
- Fill Key Ideas with 3-7 bullet points that distill ALL relevant information. Be specific — include names, numbers, concepts, and details from the notes.
- Leave Open Questions, Knowledge Gaps, Reflections, and Mind Changes with their placeholder text exactly as shown.
- The title in the markdown heading must match the "title" field in the JSON.

Notes:
{{TRANSCRIPTIONS}}

Respond in JSON format:
{
  "title": "<1 sentence title>",
  "content": "<full markdown document following the skeleton above>"
}
"""


def render_prompt(notes: list[dict]) -> str:
    transcripts = [
        {
            "voice_note_uuid": note.get("voice_note_uuid", ""),
            "transcription": note.get("raw_text", ""),
        }
        for note in notes
    ]
    transcriptions_block = json.dumps(transcripts, ensure_ascii=False)
    return SYNTHESIS_PROMPT.replace("{{TRANSCRIPTIONS}}", transcriptions_block).strip()
