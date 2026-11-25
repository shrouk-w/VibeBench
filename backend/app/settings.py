from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VB_", env_file=".env", extra="ignore")

    public: bool = False
    app_origin: str = "http://localhost:8080"
    preview_domain: str = Field(default="localhost", pattern=r"^[a-z0-9][a-z0-9.-]{0,200}$")
    preview_port: int = Field(default=8080, ge=1, le=65535)
    sandbox_enabled: bool = False
    sandbox_image: str = "vibebench-sandbox:1.2.27"
    sandbox_runtime: str = "runc"
    backend_container: str = ""
    egress_container: str = ""
    gateway_secret: str = ""
    docker_namespace: str = Field(default="local", pattern=r"^[a-z0-9-]{1,20}$")
    max_sessions: int = Field(default=1, ge=1, le=50)
    idle_seconds: int = Field(default=1200, ge=60)
    lifetime_seconds: int = Field(default=7200, ge=60)
    sandbox_memory_mb: int = Field(default=1536, ge=256)
    workspace_mb: int = Field(default=512, ge=32)
    sandbox_cache_mb: int = Field(default=384, ge=32)
    agent_state_mb: int = Field(default=128, ge=16)
    sandbox_cpus: float = Field(default=1.0, gt=0)
    sandbox_pids: int = Field(default=256, ge=32)
    export_mb: int = Field(default=48, ge=1, le=256)
    turnstile_secret: str = ""
    turnstile_hostname: str = "localhost"

    @model_validator(mode="after")
    def validate_launch(self):
        origin = urlsplit(self.app_origin)
        if (
            origin.scheme not in {"http", "https"}
            or not origin.hostname
            or origin.path
            or origin.username
            or origin.password
            or origin.query
            or origin.fragment
            or self.app_origin != f"{origin.scheme}://{origin.netloc}"
        ):
            raise ValueError("VB_APP_ORIGIN must be an HTTP origin without a path")
        if self.public:
            raise ValueError("Public launch is gated on production isolation verification")
        if self.sandbox_enabled and not (self.backend_container and self.egress_container):
            raise ValueError("Configure VB_BACKEND_CONTAINER and VB_EGRESS_CONTAINER")
        return self
