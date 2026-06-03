AGENT_MODE_ACTIVATED = "🤖 Agent mode activated"
NOTE_MODE_ACTIVATED = "📝 Note mode activated"

_REFLECT_MODE_ACTIVATED = "🧠 Reflect mode activated"


class ChatModeService:
    def __init__(self) -> None:
        self._mode = "note"

    def get_mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        assert mode in ("note", "agent", "reflect")
        self._mode = mode
