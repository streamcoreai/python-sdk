# streamcore (Python)

**English** | [简体中文](./README.zh-CN.md)

Python SDK for connecting to a [streamcore](https://github.com/streamcore/streamcore-server) server via WebRTC + WHIP, powered by [aiortc](https://github.com/aiortc/aiortc).

## Requirements

- **Python 3.10+**

## Installation

```bash
pip install streamcore
```

Or install from source:

```bash
cd python-sdk
pip install -e .
```

## Quick Start

```python
import asyncio
import numpy as np
import streamcore


async def main():
    def on_transcript(entry, all_entries):
        print(f"[{entry.role}] {entry.text}")

    client = streamcore.Client(
        config=streamcore.Config(whip_endpoint="http://localhost:8080/whip"),
        events=streamcore.EventHandler(
            on_transcript=on_transcript,
            on_error=lambda err: print(f"Error: {err}"),
        ),
    )

    await client.connect()

    # Send a 20 ms frame of silence
    pcm = np.zeros(streamcore.FRAME_SIZE, dtype=np.int16)
    await client.send_pcm(pcm)

    # Receive decoded audio from the agent
    audio = await client.recv_pcm()  # numpy int16 array

    await client.disconnect()


asyncio.run(main())
```

## API

### `Client(config?, events?)`

Creates a new voice agent client.

#### `Config`

| Field           | Type         | Default                        | Description                 |
| --------------- | ------------ | ------------------------------ | --------------------------- |
| `whip_endpoint` | `str`        | `"http://localhost:8080/whip"` | WHIP signaling endpoint URL |
| `token`         | `str`        | `""`                           | JWT sent as `Authorization: Bearer` on the WHIP request |
| `token_url`     | `str`        | `""`                           | Token endpoint; when set, a JWT is fetched before each connection (overrides `token`) |
| `api_key`       | `str`        | `""`                           | Sent as `Authorization: Bearer` when fetching from `token_url` |
| `resource_id`   | `str`        | `""`                           | Who is on the call, forwarded to an external agent so it can scope memory to the person rather than the call. Sent in the token request body when `token_url` is set (the server signs it into the token), otherwise as an `X-StreamCore-Resource-Id` header |
| `ice_servers`   | `list[str]`  | `["stun:stun.l.google.com:19302"]` | ICE server URLs        |

#### `EventHandler`

All callbacks are optional.

| Callback                 | Signature                                                       | Description                           |
| ------------------------ | --------------------------------------------------------------- | ------------------------------------- |
| `on_status_change`       | `(status: ConnectionStatus) -> None`                            | Fired when connection status changes  |
| `on_transcript`          | `(entry: TranscriptEntry, all: list[TranscriptEntry]) -> None`  | Fired on new or updated transcript    |
| `on_agent_state_change`  | `(state: AgentState) -> None`                                   | Fired when the agent starts listening, thinking, or speaking |
| `on_timing`              | `(event: TimingEvent) -> None`                                  | Fired with server-side pipeline timing info |
| `on_error`               | `(error: Exception) -> None`                                    | Fired on connection or server errors  |
| `on_data_channel_message`| `(msg: DataChannelMessage) -> None`                             | Fired for every raw DC message        |

#### Methods

| Method                          | Description                                                  |
| ------------------------------- | ------------------------------------------------------------ |
| `await client.connect(track?)`  | Connect via WHIP. Optionally pass an aiortc audio track.     |
| `await client.disconnect()`     | Tear down connection and free resources.                     |
| `await client.send_pcm(pcm)`   | Send a numpy int16 PCM buffer (mono 48 kHz) to the agent.   |
| `await client.recv_pcm()`      | Receive decoded PCM audio as a numpy int16 array.            |
| `client.status`                 | Current `ConnectionStatus`.                                  |
| `client.transcript`             | Current conversation as `list[TranscriptEntry]`.             |
| `client.remote_track`           | Inbound audio track from the agent (available after connect).|

#### Audio Constants

| Constant      | Value    | Description                      |
| ------------- | -------- | -------------------------------- |
| `SAMPLE_RATE` | `48000`  | Audio sample rate in Hz          |
| `CHANNELS`    | `1`      | Number of channels (mono)        |
| `FRAME_SIZE`  | `960`    | Samples per 20 ms frame          |

## Reconnection

A network change mid-call is recovered automatically, and the conversation
survives it: the agent still knows who you are and does not replay its
greeting.

The other SDKs run a two-phase ladder: an ICE restart first (which keeps the
transport itself alive), falling back to a resume redial once the connection
has failed. **Python has only the second phase**, and that is a hard aiortc
limit rather than a choice: `RTCPeerConnection.createOffer()` takes no options,
aioice fixes its ICE credentials at construction, and aiortc has no
`disconnected` state to act on — it goes straight from `connected` to `failed`.

So Python recovers by **redialling with a resume token**: a brand new peer
connection, reattached server-side to the session it was already running. The
transport is new; the conversation is not. In practice the difference is a
moment of silence where the other SDKs would have had none.

Status goes `connected` → `reconnecting` → `connected`:

```python
import streamcore

client = streamcore.Client(
    streamcore.Config(
        whip_endpoint="http://localhost:8080/whip",
        reconnect_attempts=3,
        reconnect_delay=2.0,
    ),
    streamcore.EventHandler(
        on_reconnect=lambda e: print(f"redial {e.attempt}/{e.max_attempts}: {e.outcome}"),
    ),
)
```

One outcome deserves handling rather than logging:

- `RECOVERED` — reattached; history intact.
- `RECOVERED_WITHOUT_HISTORY` — **the call works but the agent has forgotten
  everything.** The server had already reaped the session, so the redial
  started a fresh conversation. Surface this to the user rather than letting
  them discover it by being asked their name again.
- `FAILED` — every attempt failed; status becomes `disconnected`.

The window is the server's `session_grace_ms` (30s by default), measured from
when the connection dropped — not the ~25s ICE deadline the other SDKs work
against. Keep `reconnect_attempts × reconnect_delay` (doubling each retry)
inside it. Set `reconnect_attempts=0` to disable and handle drops yourself.

Two caveats specific to this stack:

- **Realtime (speech-to-speech) sessions cannot be resumed.** Their history
  lives inside the provider, so the server issues no token and a redial starts
  a new conversation.
- **A caller-supplied `user_track` is reused across the redial.** The built-in
  track (the `send_pcm` path) is rebuilt automatically; if you pass your own
  track to `connect()`, make sure it is still live, or reconnect yourself.

The wire-format helpers for ICE restart still ship in `streamcore.icerestart`
for callers driving another WebRTC stack:

```python
from streamcore import whip_restart_ice, ice_fragment_from_sdp, apply_ice_fragment
```

## Audio I/O

The SDK handles aiortc track management, `av.AudioFrame` construction, and
resampling internally. Callers only deal with raw PCM data as numpy int16
arrays:

```python
# Send microphone audio (960 samples = 20 ms at 48 kHz)
await client.send_pcm(pcm_int16)

# Receive agent audio
audio = await client.recv_pcm()
```

If you need direct track access (e.g. for a custom aiortc pipeline), pass
your own `AudioStreamTrack` via `client.connect(user_track=my_track)`.

## Dependencies

| Package  | Purpose                        |
| -------- | ------------------------------ |
| `aiortc` | WebRTC stack                   |
| `aiohttp`| HTTP client for WHIP signaling |
| `av`     | Audio frame encoding/decoding  |
| `numpy`  | PCM audio buffers              |

## License

Apache-2.0
