from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.agents.opencode import Agent
from app.models.catalog import Model
from app.sandboxes.docker_provider import Sandbox


class Status(StrEnum):
    CREATED = "created"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    STOPPED = "stopped"
    READY = "ready"
    FAILED = "failed"
    DESTROYED = "destroyed"


class ModelChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=200)
    api_key: SecretStr | None = None


class CreateComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=1, max_length=12_000)
    models: tuple[ModelChoice, ModelChoice]
    integrations: list[str] = Field(default_factory=list, max_length=5)
    turnstile_token: str = Field(default="", max_length=2048)


class Instruction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=1, max_length=12_000)


@dataclass
class Run:
    side: str
    model: Model
    capability: str
    password: str
    grant: str | None = None
    status: Status = Status.CREATED
    sandbox: Sandbox | None = None
    agent: Agent | None = None
    preview: bool = False
    stopping: bool = False


@dataclass
class Comparison:
    id: str
    token_digest: bytes
    prompt: str
    integrations: list[str]
    runs: dict[str, Run]
    created: float = field(default_factory=monotonic)
    activity: float = field(default_factory=monotonic)
    events: deque = field(default_factory=lambda: deque(maxlen=240))
    sequence: int = 0
    destroying: bool = False
    tasks: set = field(default_factory=set)
    provisioning: set = field(default_factory=set)
