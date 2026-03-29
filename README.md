# streamcore (Python)

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
| `ice_servers`   | `list[str]`  | `["stun:stun.l.google.com:19302"]` | ICE server URLs        |

#### `EventHandler`

| Callback                 | Signature                                                       | Description                           |
| ------------------------ | --------------------------------------------------------------- | ------------------------------------- |
| `on_status_change`       | `(status: ConnectionStatus) -> None`                            | Fired when connection status changes  |
| `on_transcript`          | `(entry: TranscriptEntry, all: list[TranscriptEntry]) -> None`  | Fired on new or updated transcript    |
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
