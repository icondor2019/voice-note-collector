from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from backend.repositories.labels_repository import LabelsRepository
from backend.repositories.repository_errors import RepositoryError, SupabaseConfigError
from backend.repositories.session_documents_repository import SessionDocumentsRepository
from backend.repositories.sources_repository import SourcesRepository
from backend.repositories.supabase_client import get_supabase_client
from backend.repositories.voice_notes_repository import VoiceNotesRepository
from backend.controllers.session_documents_controller import get_session_builder_service
from backend.models.session_document import SessionDocumentCreateRequest
from backend.services.dashboard_service import DashboardService
from backend.services.session_document_service import SessionDocumentService
from backend.services.session_builder_service import EnrichmentIncompleteError, NoValidNotesError, SessionBuilderService
from backend.services.source_service import SourceService
from backend.services.voice_note_service import VoiceNoteService
from backend.services.web_auth_service import WebAuthError, WebAuthService, WebSession
from backend.utils.web_security import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    clear_auth_cookies,
    ensure_csrf_cookie,
    new_csrf_token,
    set_auth_cookies,
    validate_csrf,
)


router = APIRouter(tags=["Web"])
PROJECT_ROOT = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "frontend" / "templates"))
PAGE_SIZE = 24


def get_web_auth_service() -> WebAuthService:
    return WebAuthService()


async def get_supabase() -> Any:
    return await get_supabase_client()


def get_sources_repository(client: Any = Depends(get_supabase)) -> SourcesRepository:
    return SourcesRepository(client)


def get_labels_repository(client: Any = Depends(get_supabase)) -> LabelsRepository:
    return LabelsRepository(client)


def get_voice_note_service(client: Any = Depends(get_supabase)) -> VoiceNoteService:
    return VoiceNoteService(
        repository=VoiceNotesRepository(client),
        source_service=SourceService(repository=SourcesRepository(client)),
    )


def get_session_document_service(
    client: Any = Depends(get_supabase),
) -> SessionDocumentService:
    return SessionDocumentService(SessionDocumentsRepository(client))


def get_dashboard_service(client: Any = Depends(get_supabase)) -> DashboardService:
    return DashboardService(
        SourcesRepository(client),
        VoiceNotesRepository(client),
        SessionDocumentsRepository(client),
    )


async def require_web_session(
    request: Request,
    response: Response,
    auth: WebAuthService = Depends(get_web_auth_service),
) -> WebSession:
    try:
        session = await auth.validate_session(
            request.cookies.get(ACCESS_COOKIE),
            request.cookies.get(REFRESH_COOKIE),
        )
    except WebAuthError as exc:
        raise HTTPException(
            status_code=303,
            detail="Authentication required",
            headers={"Location": "/login"},
        ) from exc
    if session.refreshed:
        set_auth_cookies(response, session.access_token, session.refresh_token)
    return session


async def _list_ranked_labels(labels_repo: LabelsRepository) -> list[dict[str, Any]]:
    """Use the process cache while remaining compatible with simple test doubles."""
    from backend.services.web_library_filters import label_ranking_cache

    loader = getattr(labels_repo, "list_ranked_labels", None)
    if not callable(loader):
        loader = labels_repo.list_labels
    return await label_ranking_cache.get(loader)


def _source_filter_options(sources: list[dict[str, Any]]) -> list[str]:
    types = sorted({str(source.get("type")) for source in sources if source.get("type")})
    return types


def _template(request: Request, name: str, context: dict[str, Any], status_code: int = 200) -> HTMLResponse:
    rendered = templates.TemplateResponse(
        request=request, name=name, context=context, status_code=status_code
    )
    csrf_token = context.get("csrf_token")
    if csrf_token:
        ensure_csrf_cookie(request, rendered, str(csrf_token))
    session = context.get("session")
    if isinstance(session, WebSession) and session.refreshed:
        set_auth_cookies(rendered, session.access_token, session.refresh_token)
    return rendered


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> Response:
    token = request.cookies.get(CSRF_COOKIE) or new_csrf_token()
    response = _template(request, "auth/login.html", {"error": None, "csrf_token": token})
    return response


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    auth: WebAuthService = Depends(get_web_auth_service),
) -> Response:
    validate_csrf(request, csrf_token)
    try:
        session = await auth.sign_in(email, password)
    except WebAuthError:
        return _template(
            request,
            "auth/login.html",
            {"error": "Unable to sign in with those credentials.", "csrf_token": csrf_token},
            status_code=401,
        )
    response = RedirectResponse(url="/", status_code=303)
    set_auth_cookies(response, session.access_token, session.refresh_token)
    return response


@router.post("/logout")
async def logout(
    request: Request,
    csrf_token: str = Form(...),
    auth: WebAuthService = Depends(get_web_auth_service),
) -> Response:
    validate_csrf(request, csrf_token)
    await auth.sign_out(
        request.cookies.get(ACCESS_COOKIE), request.cookies.get(REFRESH_COOKIE)
    )
    response = RedirectResponse(url="/login", status_code=303)
    clear_auth_cookies(response)
    return response


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    response: Response,
    session: WebSession = Depends(require_web_session),
    service: DashboardService = Depends(get_dashboard_service),
) -> Response:
    try:
        summary = await service.get_summary()
    except (RepositoryError, SupabaseConfigError) as exc:
        raise HTTPException(status_code=503, detail="Library unavailable") from exc
    token = ensure_csrf_cookie(request, response)
    return _template(request, "dashboard/index.html", {"session": session, "summary": summary, "csrf_token": token, "active_page": "dashboard"})


@router.get("/notes", response_class=HTMLResponse)
async def notes(
    request: Request,
    response: Response,
    source_id: Optional[str] = None,
    source_type: Optional[str] = None,
    source_author: Optional[str] = None,
    source_usage_status: Optional[str] = None,
    note_status: Optional[str] = Query(None, alias="status"),
    label_id: list[int] = Query(default=[]),
    offset: int = Query(0, ge=0),
    session: WebSession = Depends(require_web_session),
    service: VoiceNoteService = Depends(get_voice_note_service),
    sources_repo: SourcesRepository = Depends(get_sources_repository),
    labels_repo: LabelsRepository = Depends(get_labels_repository),
) -> Response:
    try:
        rows = await service.list_web_notes(
            source_id=source_id, source_type=source_type, source_author=source_author,
            source_usage_status=source_usage_status, status=note_status,
            label_ids=label_id, offset=offset, limit=PAGE_SIZE + 1,
        )
        source_options = await sources_repo.list_sources() if offset == 0 else []
        label_options = await _list_ranked_labels(labels_repo) if offset == 0 else []
    except (RepositoryError, SupabaseConfigError) as exc:
        raise HTTPException(status_code=503, detail="Library unavailable") from exc
    has_more = len(rows) > PAGE_SIZE
    next_url = str(request.url.include_query_params(offset=offset + PAGE_SIZE)) if has_more else None
    source_types = _source_filter_options(source_options)
    filters = {
        "source_id": source_id or "", "source_type": source_type or "",
        "source_author": source_author or "", "source_usage_status": source_usage_status or "",
        "status": note_status or "", "status_label": "Note status",
    }
    context = {
        "session": session, "notes": rows[:PAGE_SIZE], "sources": source_options,
        "labels": label_options, "selected_labels": label_id, "has_more": has_more,
        "next_url": next_url, "csrf_token": ensure_csrf_cookie(request, response),
        "active_page": "notes", "filters": filters,
        "source_types": source_types,
        "source_usage_statuses": ["active", "archive"],
    }
    template = "notes/_cards.html" if request.headers.get("HX-Request") == "true" else "notes/index.html"
    return _template(request, template, context)


@router.post("/notes/build", status_code=201)
async def build_notes(
    payload: SessionDocumentCreateRequest,
    request: Request,
    csrf_token: Optional[str] = Header(None, alias="X-CSRF-Token"),
    session: WebSession = Depends(require_web_session),
    service: SessionBuilderService = Depends(get_session_builder_service),
) -> dict[str, str]:
    """Build a session document from notes selected in the web library."""
    validate_csrf(request, csrf_token)
    try:
        document = await service.build(
            source_id=str(payload.source_id),
            note_ids=[str(note_id) for note_id in payload.note_ids],
        )
    except NoValidNotesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EnrichmentIncompleteError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    document_id = str(document["id"])
    return {"document_id": document_id, "redirect_url": f"/documents/{document_id}"}


@router.get("/notes/{note_id}", response_class=HTMLResponse)
async def note_detail(
    request: Request,
    response: Response,
    note_id: str,
    session: WebSession = Depends(require_web_session),
    service: VoiceNoteService = Depends(get_voice_note_service),
) -> Response:
    note = await service.get_web_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return _template(request, "notes/detail.html", {"session": session, "note": note, "csrf_token": ensure_csrf_cookie(request, response), "active_page": "notes"})


@router.get("/documents", response_class=HTMLResponse)
async def documents(
    request: Request,
    response: Response,
    source_id: Optional[str] = None,
    source_type: Optional[str] = None,
    source_author: Optional[str] = None,
    source_usage_status: Optional[str] = None,
    document_status: Optional[str] = Query(None, alias="status"),
    label_id: list[int] = Query(default=[]),
    offset: int = Query(0, ge=0),
    session: WebSession = Depends(require_web_session),
    service: SessionDocumentService = Depends(get_session_document_service),
    sources_repo: SourcesRepository = Depends(get_sources_repository),
    labels_repo: LabelsRepository = Depends(get_labels_repository),
) -> Response:
    try:
        rows = await service.list_documents(
            source_id=source_id, source_type=source_type, source_author=source_author,
            source_usage_status=source_usage_status, status=document_status,
            label_ids=label_id, offset=offset, limit=PAGE_SIZE + 1,
        )
        source_options = await sources_repo.list_sources() if offset == 0 else []
        label_options = await _list_ranked_labels(labels_repo) if offset == 0 else []
    except (RepositoryError, SupabaseConfigError) as exc:
        raise HTTPException(status_code=503, detail="Library unavailable") from exc
    has_more = len(rows) > PAGE_SIZE
    next_url = str(request.url.include_query_params(offset=offset + PAGE_SIZE)) if has_more else None
    source_types = _source_filter_options(source_options)
    filters = {
        "source_id": source_id or "", "source_type": source_type or "",
        "source_author": source_author or "", "source_usage_status": source_usage_status or "",
        "status": document_status or "", "status_label": "Document status",
    }
    context = {
        "session": session, "documents": rows[:PAGE_SIZE], "sources": source_options,
        "labels": label_options, "selected_labels": label_id, "has_more": has_more,
        "next_url": next_url, "csrf_token": ensure_csrf_cookie(request, response),
        "active_page": "documents", "filters": filters,
        "source_types": source_types,
        "source_usage_statuses": ["active", "archive"],
    }
    template = "documents/_cards.html" if request.headers.get("HX-Request") == "true" else "documents/index.html"
    return _template(request, template, context)


@router.get("/documents/{document_id}", response_class=HTMLResponse)
async def document_detail(
    request: Request,
    response: Response,
    document_id: str,
    session: WebSession = Depends(require_web_session),
    service: SessionDocumentService = Depends(get_session_document_service),
) -> Response:
    document = await service.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return _template(request, "documents/detail.html", {"session": session, "document": document, "csrf_token": ensure_csrf_cookie(request, response), "active_page": "documents"})
