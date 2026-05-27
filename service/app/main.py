# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import application_models, auth, chat, ontology, projection, repos, validation

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
app.include_router(application_models.router, prefix="/api/application-models", tags=["application-models"])


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/config")
async def get_config():
    """Public config endpoint — returns service configuration."""
    return {
        "dev_mode": settings.dev_mode,
        "oauth_enabled": bool(settings.oauth_client_id and settings.oauth_client_secret),
        "chat_model": settings.chat_model,
        "active_repo": {
            "owner": settings.github_repo_owner,
            "name": settings.github_repo_name,
        },
        "github_token": settings.dev_github_token or None,
    }

