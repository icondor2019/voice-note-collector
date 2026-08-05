from __future__ import annotations

import json

ENRICHMENT_PROMPT = """You are a note enrichment assistant. You will receive a list of voice note transcriptions and a list of available labels.

Your task:
- For each note, generate a short title (1 sentence max)
- For each note, select relevant label IDs from the available labels only — maximum 5 labels per note. You MUST NOT use label IDs not in the provided list.
- Optionally, propose new labels when the existing labels genuinely don't cover what the note is about. Most notes need zero new labels — only propose one when there's a real gap, not just because a note is slightly different from existing labels.
  Example: a note is a recipe for a vegan chocolate cake. Available labels are "cake" and "chocolate", but nothing captures that it's vegan. Since "vegan"/"veganism" is a real, reusable topic missing from the list, you may propose it as a new label.
  New label names must be: lowercase, only letters/numbers/spaces/underscores/hyphens, at most 64 characters, short and general enough to apply to future notes (not a one-off description of this single note).

Available labels:
{{AVAILABLE_LABELS}}

Notes to enrich:
{{TRANSCRIPTIONS}}

Respond with a JSON array, one object per note:
[
  {
    "voice_note_uuid": "<uuid>",
    "title": "<one sentence title>",
    "label_ids": [<id1>, <id2>],
    "new_labels": ["<optional new label name>"]
  }
]

"new_labels" should usually be an empty array [].
"""


def render_prompt(labels: list[dict], notes: list[dict]) -> str:
    label_lines = [f"- {label['id']}: {label['label']}" for label in labels]
    labels_block = "\n".join(label_lines)
    transcripts = [
        {
            "voice_note_uuid": note["voice_note_uuid"],
            "transcription": note["raw_text"],
        }
        for note in notes
    ]
    transcriptions_block = json.dumps(transcripts, ensure_ascii=False)
    return (
        ENRICHMENT_PROMPT.replace("{{AVAILABLE_LABELS}}", labels_block)
        .replace("{{TRANSCRIPTIONS}}", transcriptions_block)
        .strip()
    )
