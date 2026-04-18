"""Service configuration via environment variables."""

from pydantic_settings import BaseSettings


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

    model_config = {"env_prefix": "KAIROS_", "env_file": ".env"}


settings = Settings()
