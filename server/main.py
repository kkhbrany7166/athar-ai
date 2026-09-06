"""FastAPI entrypoint. Run one worker, bound to loopback, for local use."""
from contextlib import asynccontextmanager
import os
from typing import Annotated
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from athar.open_loops import CurrentAction
from athar.reranking import RerankedSearchResponse
from server.schemas import DecisionResponse, Health, Project, ProjectCreate, ProjectRequest, SearchRequest
from server.services import MAX_FILE_BYTES, ServiceError, WorkspaceService

ORIGINS = {"http://localhost:3000", "http://127.0.0.1:3000"}



class RequestSizeLimit:
    """Bound multipart/JSON bytes before parsing, including chunked requests."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_FILE_BYTES + 65536:
                await JSONResponse({"detail": "Request exceeds the upload limit."}, status_code=413)(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def create_app(service: WorkspaceService | None = None) -> FastAPI:
    workspaces = service or WorkspaceService()

    @asynccontextmanager
    async def lifespan(app):
        workspaces.recover()
        yield

    app = FastAPI(title="Athar AI local API", version="0.5.0", lifespan=lifespan)
    app.state.workspaces = workspaces
    app.add_middleware(RequestSizeLimit)
    app.add_middleware(CORSMiddleware, allow_origins=sorted(ORIGINS),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        # CORS alone doesn't block cross-origin form writes to an unauthenticated local API.
        origin = request.headers.get("origin")
        if origin and origin not in ORIGINS:
            return JSONResponse({"detail": "Origin is not allowed."}, status_code=403)
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > MAX_FILE_BYTES + 65536):
            return JSONResponse({"detail": "Request exceeds the upload limit."}, status_code=413)
        try:
            response = await call_next(request)
        except Exception:
            return JSONResponse({"detail": "Request could not finish. Check the local server and retry."}, status_code=500)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Default Pydantic errors include rejected input. Never echo user/provider data.
        return JSONResponse({"detail": "Invalid request. Check required fields and limits."}, status_code=422)

    @app.get("/api/health", response_model=Health)
    def health():
        return Health(ai_configured=bool(os.environ.get("OPENAI_API_KEY", "").strip()))

    @app.get("/api/projects", response_model=list[Project])
    def projects():
        return workspaces.projects()

    @app.post("/api/projects", response_model=Project, status_code=201)
    def create(body: ProjectCreate):
        return workspaces.create(body.name)

    @app.get("/api/projects/{project_id}", response_model=Project)
    def project(project_id: UUID):
        return workspaces.get(project_id)

    @app.post("/api/projects/atlas/load", response_model=Project, status_code=202)
    def atlas(background_tasks: BackgroundTasks):
        project = workspaces.atlas()
        project = workspaces.begin(project.id)
        background_tasks.add_task(workspaces.process, project.id)
        return project

    @app.post("/api/documents/upload", response_model=Project, status_code=201)
    async def upload(project_id: Annotated[UUID, Form()], file: Annotated[UploadFile, File()]):
        try:
            data = await file.read(MAX_FILE_BYTES + 1)
            return workspaces.upload(project_id, file.filename or "", data)
        finally:
            await file.close()

    @app.post("/api/process", response_model=Project, status_code=202)
    def process(body: ProjectRequest, background_tasks: BackgroundTasks):
        project = workspaces.begin(body.project_id)
        background_tasks.add_task(workspaces.process, project.id)
        return project

    @app.post("/api/search", response_model=RerankedSearchResponse)
    def search(body: SearchRequest):
        return workspaces.search(body.project_id, body.query, body.top_k)

    @app.get("/api/decisions", response_model=DecisionResponse)
    def decisions(project_id: UUID):
        return workspaces.decisions(project_id)

    @app.get("/api/actions", response_model=list[CurrentAction])
    def actions(project_id: UUID):
        return workspaces.actions(project_id)

    @app.get("/api/open-loops", response_model=list[CurrentAction])
    def loops(project_id: UUID):
        return workspaces.actions(project_id, unresolved_only=True)

    @app.get("/api/actions/{action_id}", response_model=CurrentAction)
    def action(action_id: str, project_id: UUID):
        result = next((a for a in workspaces.actions(project_id) if a.action.id == action_id), None)
        if result is None:
            raise ServiceError("Action not found.", 404)
        return result

    return app


app = create_app()
