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


@dataclass
class DataChannelMessage:
    type: str  # "transcript", "response", or "error"
    text: str = ""
    final: bool = False
    message: str = ""  # for error type


@dataclass
class Config:
    """Configuration for a StreamCoreAIClient."""

    whip_endpoint: str = "http://localhost:8080/whip"
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
    on_data_channel_message: Callable[[DataChannelMessage], None] | None = None
