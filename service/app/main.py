"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import chat, ontology, projection, validation

app = FastAPI(
    title="Kairos Ontology Service",
    version="0.2.0",
    description=(
        "REST API for ontology CRUD, validation, projection, and AI chat. "
        "Chat is powered by the GitHub Copilot SDK with custom ontology tools."
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


@app.get("/health")
async def health():
    return {"status": "ok"}
