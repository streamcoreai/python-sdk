from __future__ import annotations

import asyncio
import json
import logging
from threading import Lock

import aiohttp
import av
import numpy as np
from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.contrib.media import MediaBlackhole

from .audio import SAMPLE_RATE, _SDKAudioTrack
from .types import (
    AgentState,
    Config,
    ConnectionStatus,
    DataChannelMessage,
    EventHandler,
    TimingEvent,
    TranscriptEntry,
)
from .whip import whip_delete, whip_offer

logger = logging.getLogger("streamcore")


class Client:
    """Manages a WebRTC connection to a Voice Agent server via WHIP signaling.

    After :meth:`connect` returns, the peer connection is active. Remote audio
    is consumed internally (or via the ``remote_track`` attribute). Provide an
    audio track via ``user_track`` to send microphone audio to the server.
    """

    def __init__(
        self,
        config: Config | None = None,
        events: EventHandler | None = None,
    ) -> None:
        self.config = config or Config()
        self.events = events or EventHandler()

        self._pc: RTCPeerConnection | None = None
        self._session_url: str = ""
        self._blackhole: MediaBlackhole | None = None

        self._lock = Lock()
        self._status = ConnectionStatus.IDLE
        self._transcript: list[TranscriptEntry] = []
        self._assist_buf: str = ""

        self.remote_track = None
        """The inbound audio track from the agent, available after connect."""

        self._sdk_track: _SDKAudioTrack | None = None
        self._remote_track_ready = asyncio.Event()
        self._resampler: av.AudioResampler | None = None

    @property
    def status(self) -> ConnectionStatus:
        with self._lock:
            return self._status

    @property
    def transcript(self) -> list[TranscriptEntry]:
        with self._lock:
            return list(self._transcript)

    async def connect(self, user_track=None) -> None:
        """Establish a WebRTC connection to the voice agent server.

        Args:
            user_track: An optional aiortc MediaStreamTrack for the user's
                microphone audio. If provided it will be added to the peer
                connection so the server receives audio from the user.
        """
        self._set_status(ConnectionStatus.CONNECTING)

        try:
            ice_servers = [RTCIceServer(urls=url) for url in self.config.ice_servers]
            pc = RTCPeerConnection(RTCConfiguration(iceServers=ice_servers))
            self._pc = pc

            # Add user audio track if provided, otherwise create SDK track.
            if user_track is not None:
                pc.addTrack(user_track)
            else:
                self._sdk_track = _SDKAudioTrack()
                pc.addTrack(self._sdk_track)

            # Create data channel for receiving events from the server.
            dc = pc.createDataChannel("events")

            @dc.on("message")
            def on_dc_message(message):
                try:
                    data = json.loads(message)
                    msg = DataChannelMessage(
                        type=data.get("type", ""),
                        text=data.get("text", ""),
                        final=data.get("final", False),
                        message=data.get("message", ""),
                        stage=data.get("stage", ""),
                        ms=data.get("ms", 0),
                        state=data.get("state", ""),
                    )
                    if self.events.on_data_channel_message:
                        self.events.on_data_channel_message(msg)
                    self._handle_data_channel_message(msg)
                except Exception as exc:
                    logger.warning("Failed to parse DC message: %s", exc)

            @pc.on("track")
            def on_track(track):
                self.remote_track = track
                self._remote_track_ready.set()

            @pc.on("connectionstatechange")
            async def on_connection_state_change():
                state = pc.connectionState
                if state == "connected":
                    self._set_status(ConnectionStatus.CONNECTED)
                elif state in ("failed", "closed", "disconnected"):
                    self._set_status(ConnectionStatus.DISCONNECTED)

            # Create offer and gather ICE candidates.
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)

            # aiortc gathers ICE candidates during setLocalDescription,
            # so localDescription.sdp already contains all candidates.
            offer_sdp = pc.localDescription.sdp

            # Fetch a fresh token from the token endpoint if configured.
            token = self.config.token
            if self.config.token_url:
                fetch_headers: dict[str, str] = {}
                if self.config.api_key:
                    fetch_headers["Authorization"] = f"Bearer {self.config.api_key}"
                async with aiohttp.ClientSession() as http_session:
                    async with http_session.post(self.config.token_url, headers=fetch_headers) as resp:
                        if resp.status != 200:
                            raise RuntimeError(f"Token request failed ({resp.status})")
                        data = await resp.json()
                        token = data["token"]

            # WHIP exchange.
            result = await whip_offer(self.config.whip_endpoint, offer_sdp, token)
            self._session_url = result.session_url

            answer = RTCSessionDescription(sdp=result.answer_sdp, type="answer")
            await pc.setRemoteDescription(answer)

        except Exception as exc:
            logger.error("Connect error: %s", exc)
            self._set_status(ConnectionStatus.ERROR)
            if self.events.on_error:
                self.events.on_error(exc)
            raise

    async def disconnect(self) -> None:
        """Tear down the WebRTC connection and free resources."""
        # Stop SDK track first so aiortc's internal consumer unblocks.
        if self._sdk_track is not None:
            self._sdk_track.stop()
            self._sdk_track = None
        await whip_delete(self._session_url, self.config.token)
        self._session_url = ""
        if self._blackhole:
            await self._blackhole.stop()
            self._blackhole = None
        if self._pc:
            pc = self._pc
            self._pc = None
            try:
                await asyncio.wait_for(pc.close(), timeout=3)
            except (asyncio.TimeoutError, Exception):
                pass
        self._remote_track_ready.clear()
        self._resampler = None
        self._set_status(ConnectionStatus.IDLE)
        self._assist_buf = ""

    # ── Audio helpers ────────────────────────────────────────────────

    async def send_pcm(self, pcm: np.ndarray) -> None:
        """Send a buffer of 16-bit PCM samples to the voice agent.

        Args:
            pcm: numpy int16 array of audio samples (mono, 48 kHz).
                 Typically ``FRAME_SIZE`` (960) samples for a 20 ms frame.
        """
        if self._sdk_track is None:
            raise RuntimeError(
                "send_pcm requires the built-in audio track; "
                "do not pass user_track to connect()"
            )
        await self._sdk_track._queue.put(pcm)

    async def recv_pcm(self) -> np.ndarray:
        """Receive decoded PCM audio from the voice agent.

        Blocks until the remote audio track is available, then returns
        a numpy int16 array of mono 48 kHz samples.
        """
        await self._remote_track_ready.wait()
        track = self.remote_track

        if self._resampler is None:
            self._resampler = av.AudioResampler(
                format="s16", layout="mono", rate=SAMPLE_RATE
            )

        frame = await track.recv()
        arrays = []
        for resampled in self._resampler.resample(frame):
            arrays.append(resampled.to_ndarray().flatten())
        if arrays:
            return np.concatenate(arrays)
        return np.array([], dtype=np.int16)

    # ── Internal helpers ─────────────────────────────────────────────

    def _set_status(self, status: ConnectionStatus) -> None:
        with self._lock:
            self._status = status
        if self.events.on_status_change:
            self.events.on_status_change(status)

    def _handle_data_channel_message(self, msg: DataChannelMessage) -> None:
        with self._lock:
            if msg.type == "transcript":
                if msg.final:
                    pending_assistant = self._assist_buf
                    self._assist_buf = ""

                    updated = [
                        e
                        for e in self._transcript
                        if not (e.role == "user" and e.partial)
                        and not (e.role == "assistant" and e.partial)
                    ]
                    if pending_assistant:
                        updated.append(
                            TranscriptEntry(role="assistant", text=pending_assistant)
                        )
                    updated.append(TranscriptEntry(role="user", text=msg.text))
                    self._transcript = updated
                else:
                    updated = [
                        e
                        for e in self._transcript
                        if not (e.role == "user" and e.partial)
                    ]
                    updated.append(
                        TranscriptEntry(role="user", text=msg.text, partial=True)
                    )
                    self._transcript = updated

                entry = self._transcript[-1]
                all_entries = list(self._transcript)

            elif msg.type == "response":
                self._assist_buf += msg.text
                current_text = self._assist_buf

                updated = [
                    e
                    for e in self._transcript
                    if not (e.role == "assistant" and e.partial)
                ]
                updated.append(
                    TranscriptEntry(role="assistant", text=current_text, partial=True)
                )
                self._transcript = updated

                entry = self._transcript[-1]
                all_entries = list(self._transcript)

            elif msg.type == "error":
                logger.error("Server error: %s", msg.message)
                if self.events.on_error:
                    self.events.on_error(RuntimeError(msg.message))
                return

            elif msg.type == "timing":
                if self.events.on_timing and msg.stage:
                    self.events.on_timing(TimingEvent(stage=msg.stage, ms=msg.ms))
                return

            elif msg.type == "state":
                if self.events.on_agent_state_change and msg.state:
                    try:
                        self.events.on_agent_state_change(AgentState(msg.state))
                    except ValueError:
                        logger.warning("Unknown agent state: %s", msg.state)
                return
            else:
                return

        if self.events.on_transcript:
            self.events.on_transcript(entry, all_entries)
