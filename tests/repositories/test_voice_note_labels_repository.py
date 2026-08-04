from __future__ import annotations

from typing import Any, Optional

import pytest

from backend.repositories.repository_errors import RepositoryError
from backend.repositories.voice_note_labels_repository import VoiceNoteLabelsRepository


class _StubResponse:
    def __init__(self, data: Any = None, error: Optional[str] = None) -> None:
        self.data = data
        self.error = error


class _StubQuery:
    def __init__(self, response: _StubResponse, table: "_StubTable") -> None:
        self._response = response
        self._table = table

    def select(self, *args: Any, **kwargs: Any) -> _StubQuery:
        self._table.selected = args[0] if args else None
        return self

    def eq(self, column: str, value: Any) -> _StubQuery:
        self._table.filters.append(("eq", column, value))
        return self

    def in_(self, column: str, values: Any) -> _StubQuery:
        self._table.filters.append(("in", column, values))
        return self

    def is_(self, column: str, value: Any) -> _StubQuery:
        self._table.filters.append(("is", column, value))
        return self

    def maybe_single(self) -> _StubQuery:
        return self

    async def execute(self) -> _StubResponse:
        return self._response


class _StubTable:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response
        self.insert_payload: Optional[dict[str, Any]] = None
        self.update_payload: Optional[dict[str, Any]] = None
        self.selected: Optional[str] = None
        self.filters: list[tuple[str, str, Any]] = []

    def insert(self, payload: dict[str, Any]) -> _StubQuery:
        self.insert_payload = payload
        return _StubQuery(self._response, self)

    def update(self, payload: dict[str, Any]) -> _StubQuery:
        self.update_payload = payload
        return _StubQuery(self._response, self)

    def select(self, *args: Any, **kwargs: Any) -> _StubQuery:
        self.selected = args[0] if args else None
        return _StubQuery(self._response, self)


class _StubClient:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response
        self.table_name: Optional[str] = None
        self.table_instance: Optional[_StubTable] = None

    def table(self, table_name: str) -> _StubTable:
        self.table_name = table_name
        self.table_instance = _StubTable(self._response)
        return self.table_instance


class _SequencedClient:
    """Returns a different stubbed response per table() call, in order."""

    def __init__(self, responses: list[_StubResponse]) -> None:
        self._responses = responses
        self.tables: list[_StubTable] = []

    def table(self, table_name: str) -> _StubTable:
        response = self._responses[len(self.tables)]
        table = _StubTable(response)
        self.tables.append(table)
        return table


class TestAttachLabel:
    @pytest.mark.anyio
    async def test_inserts_when_pairing_absent(self) -> None:
        inserted = {"id": "pair-1", "voice_note_uuid": "note-1", "label_id": 3}
        client = _SequencedClient(
            [
                _StubResponse(data=[]),
                _StubResponse(data=inserted),
            ]
        )
        repository = VoiceNoteLabelsRepository(client)

        result = await repository.attach_label("note-1", 3, applied_by="user")

        assert result == inserted
        assert client.tables[1].insert_payload == {
            "voice_note_uuid": "note-1",
            "label_id": 3,
            "applied_by": "user",
        }

    @pytest.mark.anyio
    async def test_revives_soft_deleted_pairing(self) -> None:
        archived = {
            "id": "pair-1",
            "voice_note_uuid": "note-1",
            "label_id": 3,
            "deleted_at": "2026-01-01T00:00:00",
        }
        revived = {**archived, "deleted_at": None}
        client = _SequencedClient(
            [
                _StubResponse(data=[archived]),
                _StubResponse(data=revived),
            ]
        )
        repository = VoiceNoteLabelsRepository(client)

        result = await repository.attach_label("note-1", 3, applied_by="user")

        assert result == revived
        assert client.tables[1].insert_payload is None
        assert client.tables[1].update_payload == {
            "deleted_at": None,
            "applied_by": "user",
        }

    @pytest.mark.anyio
    async def test_revives_most_recent_archived_pairing(self) -> None:
        older = {"id": "pair-1", "label_id": 3, "deleted_at": "2026-01-01T00:00:00"}
        newer = {"id": "pair-2", "label_id": 3, "deleted_at": "2026-06-01T00:00:00"}
        client = _SequencedClient(
            [
                _StubResponse(data=[older, newer]),
                _StubResponse(data={"id": "pair-2", "deleted_at": None}),
            ]
        )
        repository = VoiceNoteLabelsRepository(client)

        await repository.attach_label("note-1", 3)

        assert ("eq", "id", "pair-2") in client.tables[1].filters

    @pytest.mark.anyio
    async def test_noops_when_already_active(self) -> None:
        active = {"id": "pair-1", "label_id": 3, "deleted_at": None}
        client = _SequencedClient([_StubResponse(data=[active])])
        repository = VoiceNoteLabelsRepository(client)

        result = await repository.attach_label("note-1", 3)

        assert result == active
        assert len(client.tables) == 1

    @pytest.mark.anyio
    async def test_defaults_to_llm_provenance(self) -> None:
        client = _SequencedClient(
            [_StubResponse(data=[]), _StubResponse(data={"id": "pair-1"})]
        )
        repository = VoiceNoteLabelsRepository(client)

        await repository.attach_label("note-1", 3)

        assert client.tables[1].insert_payload is not None
        assert client.tables[1].insert_payload["applied_by"] == "llm"

    @pytest.mark.anyio
    async def test_raises_when_insert_returns_nothing(self) -> None:
        client = _SequencedClient([_StubResponse(data=[]), _StubResponse(data=None)])
        repository = VoiceNoteLabelsRepository(client)

        with pytest.raises(RepositoryError):
            await repository.attach_label("note-1", 3)

    @pytest.mark.anyio
    async def test_raises_on_client_error(self) -> None:
        client = _StubClient(_StubResponse(error="boom"))
        repository = VoiceNoteLabelsRepository(client)

        with pytest.raises(RepositoryError):
            await repository.attach_label("note-1", 3)


class TestDetachLabel:
    @pytest.mark.anyio
    async def test_sets_deleted_at_without_hard_delete(self) -> None:
        response = _StubResponse(data={"id": "pair-1", "deleted_at": "2026-08-03"})
        client = _StubClient(response)
        repository = VoiceNoteLabelsRepository(client)

        result = await repository.detach_label("note-1", 3)

        assert result == response.data
        assert client.table_name == "voice_note_labels"
        assert client.table_instance is not None
        payload = client.table_instance.update_payload
        assert payload is not None
        assert payload["deleted_at"] is not None
        assert ("is", "deleted_at", "null") in client.table_instance.filters

    @pytest.mark.anyio
    async def test_returns_none_when_nothing_active(self) -> None:
        client = _StubClient(_StubResponse(data=[]))
        repository = VoiceNoteLabelsRepository(client)

        result = await repository.detach_label("note-1", 3)

        assert result is None

    @pytest.mark.anyio
    async def test_raises_on_client_error(self) -> None:
        client = _StubClient(_StubResponse(error="boom"))
        repository = VoiceNoteLabelsRepository(client)

        with pytest.raises(RepositoryError):
            await repository.detach_label("note-1", 3)


class TestListLabelsForNote:
    @pytest.mark.anyio
    async def test_filters_out_soft_deleted(self) -> None:
        rows = [{"label_id": 1, "labels": {"id": 1, "label": "ideas"}}]
        client = _StubClient(_StubResponse(data=rows))
        repository = VoiceNoteLabelsRepository(client)

        result = await repository.list_labels_for_note("note-1")

        assert result == rows
        assert client.table_instance is not None
        assert ("is", "deleted_at", "null") in client.table_instance.filters
        assert client.table_instance.selected == "*, labels(id, label)"

    @pytest.mark.anyio
    async def test_returns_empty_list_when_no_rows(self) -> None:
        client = _StubClient(_StubResponse(data=[]))
        repository = VoiceNoteLabelsRepository(client)

        assert await repository.list_labels_for_note("note-1") == []

    @pytest.mark.anyio
    async def test_raises_on_client_error(self) -> None:
        client = _StubClient(_StubResponse(error="boom"))
        repository = VoiceNoteLabelsRepository(client)

        with pytest.raises(RepositoryError):
            await repository.list_labels_for_note("note-1")


class TestListNotesByLabel:
    @pytest.mark.anyio
    async def test_returns_note_uuids(self) -> None:
        rows = [{"voice_note_uuid": "note-1"}, {"voice_note_uuid": "note-2"}]
        client = _StubClient(_StubResponse(data=rows))
        repository = VoiceNoteLabelsRepository(client)

        result = await repository.list_notes_by_label(3)

        assert result == ["note-1", "note-2"]
        assert client.table_instance is not None
        assert ("eq", "label_id", 3) in client.table_instance.filters
        assert ("is", "deleted_at", "null") in client.table_instance.filters

    @pytest.mark.anyio
    async def test_returns_empty_list_when_label_unused(self) -> None:
        client = _StubClient(_StubResponse(data=[]))
        repository = VoiceNoteLabelsRepository(client)

        assert await repository.list_notes_by_label(3) == []

    @pytest.mark.anyio
    async def test_raises_on_client_error(self) -> None:
        client = _StubClient(_StubResponse(error="boom"))
        repository = VoiceNoteLabelsRepository(client)

        with pytest.raises(RepositoryError):
            await repository.list_notes_by_label(3)


class TestListLabelsForNotes:
    @pytest.mark.anyio
    async def test_groups_rows_by_note_uuid(self) -> None:
        rows = [
            {"voice_note_uuid": "note-1", "label_id": 1},
            {"voice_note_uuid": "note-1", "label_id": 2},
            {"voice_note_uuid": "note-2", "label_id": 1},
        ]
        client = _StubClient(_StubResponse(data=rows))
        repository = VoiceNoteLabelsRepository(client)

        result = await repository.list_labels_for_notes(["note-1", "note-2"])

        assert result == {
            "note-1": [rows[0], rows[1]],
            "note-2": [rows[2]],
        }

    @pytest.mark.anyio
    async def test_empty_input_skips_query(self) -> None:
        client = _StubClient(_StubResponse(error="should not be queried"))
        repository = VoiceNoteLabelsRepository(client)

        assert await repository.list_labels_for_notes([]) == {}
        assert client.table_name is None

    @pytest.mark.anyio
    async def test_omits_notes_without_labels(self) -> None:
        client = _StubClient(_StubResponse(data=[{"voice_note_uuid": "note-1"}]))
        repository = VoiceNoteLabelsRepository(client)

        result = await repository.list_labels_for_notes(["note-1", "note-2"])

        assert "note-2" not in result

    @pytest.mark.anyio
    async def test_raises_on_client_error(self) -> None:
        client = _StubClient(_StubResponse(error="boom"))
        repository = VoiceNoteLabelsRepository(client)

        with pytest.raises(RepositoryError):
            await repository.list_labels_for_notes(["note-1"])


class TestReplaceLlmLabels:
    @pytest.mark.anyio
    async def test_detaches_dropped_llm_labels_and_attaches_new(self) -> None:
        active = [
            {"label_id": 1, "applied_by": "llm", "deleted_at": None},
            {"label_id": 2, "applied_by": "llm", "deleted_at": None},
        ]
        client = _SequencedClient(
            [
                _StubResponse(data=active),  # _list_active_pairings
                _StubResponse(data={"label_id": 2}),  # detach 2
                _StubResponse(data=[]),  # _find_pairing for 3
                _StubResponse(data={"label_id": 3}),  # insert 3
            ]
        )
        repository = VoiceNoteLabelsRepository(client)

        result = await repository.replace_llm_labels("note-1", [1, 3])

        assert result == {"attached": [3], "detached": [2]}

    @pytest.mark.anyio
    async def test_leaves_user_applied_labels_intact(self) -> None:
        active = [
            {"label_id": 1, "applied_by": "user", "deleted_at": None},
            {"label_id": 2, "applied_by": "llm", "deleted_at": None},
        ]
        client = _SequencedClient(
            [
                _StubResponse(data=active),
                _StubResponse(data={"label_id": 2}),  # detach 2 (llm, dropped)
            ]
        )
        repository = VoiceNoteLabelsRepository(client)

        result = await repository.replace_llm_labels("note-1", [])

        assert result == {"attached": [], "detached": [2]}
        assert len(client.tables) == 2

    @pytest.mark.anyio
    async def test_does_not_reattach_label_already_active_as_user(self) -> None:
        active = [{"label_id": 1, "applied_by": "user", "deleted_at": None}]
        client = _SequencedClient([_StubResponse(data=active)])
        repository = VoiceNoteLabelsRepository(client)

        result = await repository.replace_llm_labels("note-1", [1])

        assert result == {"attached": [], "detached": []}
        assert len(client.tables) == 1

    @pytest.mark.anyio
    async def test_no_changes_when_labels_match(self) -> None:
        active = [{"label_id": 1, "applied_by": "llm", "deleted_at": None}]
        client = _SequencedClient([_StubResponse(data=active)])
        repository = VoiceNoteLabelsRepository(client)

        result = await repository.replace_llm_labels("note-1", [1])

        assert result == {"attached": [], "detached": []}

    @pytest.mark.anyio
    async def test_attaches_all_when_note_has_no_labels(self) -> None:
        client = _SequencedClient(
            [
                _StubResponse(data=[]),  # no active pairings
                _StubResponse(data=[]),  # _find_pairing for 7
                _StubResponse(data={"label_id": 7}),  # insert 7
            ]
        )
        repository = VoiceNoteLabelsRepository(client)

        result = await repository.replace_llm_labels("note-1", [7])

        assert result == {"attached": [7], "detached": []}
        assert client.tables[2].insert_payload is not None
        assert client.tables[2].insert_payload["applied_by"] == "llm"

    @pytest.mark.anyio
    async def test_duplicate_label_ids_attached_once(self) -> None:
        client = _SequencedClient(
            [
                _StubResponse(data=[]),  # no active pairings
                _StubResponse(data=[]),  # _find_pairing for 7
                _StubResponse(data={"label_id": 7}),  # insert 7
            ]
        )
        repository = VoiceNoteLabelsRepository(client)

        result = await repository.replace_llm_labels("note-1", [7, 7])

        assert result == {"attached": [7], "detached": []}
        assert len(client.tables) == 3

    @pytest.mark.anyio
    async def test_raises_on_client_error(self) -> None:
        client = _StubClient(_StubResponse(error="boom"))
        repository = VoiceNoteLabelsRepository(client)

        with pytest.raises(RepositoryError):
            await repository.replace_llm_labels("note-1", [1])
