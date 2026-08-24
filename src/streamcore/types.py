from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class ConnectionStatus(str, Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    #: The transport is gone and the client is redialling with a resume token.
    #: The conversation is still alive on the server, so this is not terminal.
    RECONNECTING = "reconnecting"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class ReconnectOutcome(str, Enum):
    ATTEMPTING = "attempting"
    #: Reattached to the same server-side conversation.
    RECOVERED = "recovered"
    #: Reconnected, but the server could not resume — this is a fresh
    #: conversation and the agent has no memory of what came before.
    RECOVERED_WITHOUT_HISTORY = "recovered_without_history"
    FAILED = "failed"


@dataclass
class ReconnectEvent:
    """Progress of the redial sequence after a dropped connection."""

    attempt: int  # 1-based
    max_attempts: int
    outcome: ReconnectOutcome
    error: Exception | None = None


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
    type: str  # "transcript", "response", "error", "timing", "state", or "data"
    text: str = ""
    final: bool = False
    message: str = ""  # for error type
    stage: str = ""  # for timing type
    ms: int = 0  # for timing type
    state: str = ""  # for state type
    topic: str = ""  # for data type
    payload: str = ""  # for data type; base64-encoded JSON


@dataclass
class Config:
    """Configuration for a StreamCoreAIClient."""

    whip_endpoint: str = "http://localhost:8080/whip"
    token: str = ""  # JWT token for authenticating with the WHIP endpoint
    token_url: str = ""  # Token endpoint URL; if set, fetches a JWT before each connection (overrides token)
    api_key: str = ""  # API key sent as Bearer header when fetching from token_url

    #: Who is on the call: an app user ID, or the number a phone call came
    #: from. The server passes it to an external agent, which can then remember
    #: a caller across separate calls.
    #:
    #: With ``token_url`` set it goes in the token request body and the server
    #: signs it into the token. Otherwise it goes as a header, which the server
    #: only trusts when there is no signed claim.
    resource_id: str = ""

    ice_servers: list[str] = field(
        default_factory=lambda: ["stun:stun.l.google.com:19302"]
    )

    #: How many times to redial after a dropped connection. aiortc cannot
    #: perform an ICE restart, so recovery here means a fresh peer connection
    #: carrying the session's resume token — which keeps the *conversation*
    #: even though the transport is new. 0 disables automatic reconnection.
    reconnect_attempts: int = 3

    #: Delay before the first redial, doubling for each retry. Unlike the ICE
    #: restart path in the other SDKs there is no ~25s deadline to fit inside:
    #: the server holds the conversation for ``server.session_grace_ms``
    #: (30s by default), so keep the total under that.
    reconnect_delay: float = 2.0


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
    #: Called for a topic-addressed packet from a device-side tool, with the
    #: payload already base64-decoded. The server sends these fire-and-forget
    #: — it has already told the model the action succeeded — so there is
    #: nothing to reply to. Locomotion commands from the ``movement.*`` tools
    #: arrive on the ``movement.command`` topic.
    on_data: Callable[[str, bytes], None] | None = None
    #: Called for each redial attempt and once when the outcome is known.
    #: Watch for RECOVERED_WITHOUT_HISTORY — the call works, but the agent has
    #: forgotten the conversation and your UI may want to say so.
    on_reconnect: Callable[[ReconnectEvent], None] | None = None
