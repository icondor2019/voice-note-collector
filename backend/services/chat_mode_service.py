AGENT_MODE_ACTIVATED = "🤖 Agent mode activated"
NOTE_MODE_ACTIVATED = "📝 Note mode activated"


class ChatModeService:
    def __init__(self) -> None:
        self._mode = "note"

    def get_mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        assert mode in ("note", "agent")
        self._mode = mode
