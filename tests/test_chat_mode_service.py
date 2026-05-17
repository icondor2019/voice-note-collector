from backend.services.chat_mode_service import ChatModeService


def test_chat_mode_service_defaults_to_note() -> None:
    service = ChatModeService()

    assert service.get_mode() == "note"


def test_chat_mode_service_set_agent() -> None:
    service = ChatModeService()

    service.set_mode("agent")

    assert service.get_mode() == "agent"


def test_chat_mode_service_set_note() -> None:
    service = ChatModeService()

    service.set_mode("agent")
    service.set_mode("note")

    assert service.get_mode() == "note"
