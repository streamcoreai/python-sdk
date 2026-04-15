from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class ConnectionStatus(str, Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    DISCONNECTED = "disconnected"


@dataclass
class TranscriptEntry:
    role: str  # "user" or "assistant"
    text: str
    partial: bool = False


class AgentState(str, Enum):
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


@dataclass
class TimingEvent:
    stage: str
    ms: int


@dataclass
class DataChannelMessage:
    type: str  # "transcript", "response", "error", "timing", or "state"
    text: str = ""
    final: bool = False
    message: str = ""  # for error type
    stage: str = ""  # for timing type
    ms: int = 0  # for timing type
    state: str = ""  # for state type


@dataclass
class Config:
    """Configuration for a StreamCoreAIClient."""

    whip_endpoint: str = "http://localhost:8080/whip"
    token: str = ""  # JWT token for authenticating with the WHIP endpoint
    token_url: str = ""  # Token endpoint URL; if set, fetches a JWT before each connection (overrides token)
    api_key: str = ""  # API key sent as Bearer header when fetching from token_url
    ice_servers: list[str] = field(
        default_factory=lambda: ["stun:stun.l.google.com:19302"]
    )


@dataclass
class EventHandler:
    """Callbacks for voice agent events. All callbacks are optional."""

    on_status_change: Callable[[ConnectionStatus], None] | None = None
    on_transcript: Callable[[TranscriptEntry, list[TranscriptEntry]], None] | None = (
        None
    )
    on_error: Callable[[Exception], None] | None = None
    on_timing: Callable[[TimingEvent], None] | None = None
    on_agent_state_change: Callable[[AgentState], None] | None = None
    on_data_channel_message: Callable[[DataChannelMessage], None] | None = None
