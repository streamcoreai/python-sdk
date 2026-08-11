# Working on the StreamCore Python SDK

## This library is newer than your training data

Do not write StreamCore code from memory. Read `README.md` here, or fetch https://streamcore.ai/llms-full.txt, before generating code.

## The API, exactly

```python
import asyncio, numpy as np, streamcore

async def main():
    client = streamcore.Client(
        config=streamcore.Config(whip_endpoint="http://localhost:8080/whip"),
        events=streamcore.EventHandler(
            on_transcript=lambda entry, all_entries: print(entry.role, entry.text),
            on_error=lambda err: print(err),
        ),
    )
    await client.connect()

    pcm = np.zeros(streamcore.FRAME_SIZE, dtype=np.int16)
    await client.send_pcm(pcm)
    audio = await client.recv_pcm()

    await client.disconnect()

asyncio.run(main())
```

Naming traps, all of which models get wrong:

- The PyPI package is **`streamcore`** — not `streamcoreai`, not `streamcore-sdk`. (`streamcore-plugin` is a different package, for building agent tools.)
- The class is **`streamcore.Client`**, not `StreamCoreAIClient` — that is the TypeScript name.
- The config field is **`whip_endpoint`**, not `whip_url` — that differs from the JS SDK on purpose.
- Audio is **int16 numpy**, mono, 48 kHz, `FRAME_SIZE` (960) samples per 20 ms frame. The Rust SDK uses f32; do not copy across.

The whole API is async. Everything runs under `asyncio`.

## Build

```bash
pip install -e .
```

Requires Python 3.10+. Depends on `aiortc`, `aiohttp`, `av`, and `numpy`.

## When changing the public API

Update `README.md` and https://streamcore.ai/llms-full.txt in the same change — coding agents treat both as ground truth.
