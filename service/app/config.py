"""Service configuration via environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings

# Resolve .env relative to the service/ directory, not cwd
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """All settings are read from environment variables (or a .env file)."""

    # GitHub App credentials
    github_app_id: str = ""
    github_app_private_key: str = ""  # PEM content or path
    github_installation_id: str = ""

    # Repo to operate on
    github_repo_owner: str = ""
    github_repo_name: str = ""
    github_default_branch: str = "main"
    github_ontologies_path: str = "ontologies"

    # Service
    allowed_origins: str = "*"  # comma-separated CORS origins
    dev_mode: bool = False  # use local files instead of GitHub API
    local_ontologies_dir: str = "ontologies"  # path to local TTL files (dev mode)
    dev_github_token: str = ""  # GitHub PAT for Copilot SDK in dev mode

    model_config = {"env_prefix": "KAIROS_", "env_file": str(_ENV_FILE)}


settings = Settings()


def get_github_service():
    """Return the appropriate file-access service module.

    In dev mode, returns ``local_service`` which reads from disk.
    Otherwise returns ``github_service`` which calls the GitHub API.
    """
    if settings.dev_mode:
        from .services import local_service

        return local_service
    from .services import github_service

    return github_service
