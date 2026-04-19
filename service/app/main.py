"""FastAPI application entry point."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routers import auth, chat, ontology, projection, repos, validation

app = FastAPI(
    title="Kairos Ontology Service",
    version="0.2.0",
    description=(
        "REST API for ontology CRUD, validation, projection, and AI chat. "
        "Chat is powered by the GitHub Models API with custom ontology tools."
    ),
)

# CORS
origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(ontology.router, prefix="/api/ontology", tags=["ontology"])
app.include_router(validation.router, prefix="/api/validate", tags=["validation"])
app.include_router(projection.router, prefix="/api/project", tags=["projection"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(repos.router, prefix="/api/repos", tags=["repos"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/config")
async def get_config():
    """Public config endpoint — tells the UI about dev mode and active repo."""
    return {
        "dev_mode": settings.dev_mode,
        "oauth_enabled": bool(settings.oauth_client_id and settings.oauth_client_secret),
        "chat_model": settings.chat_model,
        "active_repo": {
            "owner": settings.github_repo_owner,
            "name": settings.github_repo_name,
        },
    }


# Static UI — prefer the compiled React/Vite build, fall back to legacy static/
_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
_static_dir = Path(__file__).resolve().parent.parent / "static"

_ui_dir = _frontend_dist if _frontend_dist.is_dir() else _static_dir

if _ui_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_ui_dir / "assets")), name="assets") \
        if (_ui_dir / "assets").is_dir() else None
    app.mount("/static", StaticFiles(directory=str(_ui_dir)), name="static")

    @app.get("/")
    async def root():
        return FileResponse(str(_ui_dir / "index.html"))

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        """Return index.html for any non-API route (SPA client-side routing)."""
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404)
        index = _ui_dir / "index.html"
        if index.is_file():
            return FileResponse(str(index))
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
