"""Audio helpers for the StreamCoreAI Python SDK.

Provides PCM-level send/receive so callers never need to deal with
aiortc tracks, av.AudioFrame construction, or resampling.
"""

from __future__ import annotations

import asyncio
import fractions

import av
import numpy as np
from aiortc.mediastreams import AudioStreamTrack, MediaStreamError

SAMPLE_RATE: int = 48_000
"""Audio sample rate in Hz (48 kHz)."""

CHANNELS: int = 1
"""Number of audio channels (mono)."""

FRAME_SIZE: int = 960
"""Number of samples per 20 ms frame at 48 kHz."""


class _SDKAudioTrack(AudioStreamTrack):
    """Internal aiortc track fed by :meth:`Client.send_pcm`."""

    kind = "audio"

    def __init__(self) -> None:
        super().__init__()
        self._queue: asyncio.Queue[np.ndarray] = asyncio.Queue()
        self._samples: int = 0
        self._time_base = fractions.Fraction(1, SAMPLE_RATE)

    async def recv(self) -> av.AudioFrame:
        if self.readyState != "live":
            raise MediaStreamError
        try:
            pcm = await asyncio.wait_for(self._queue.get(), timeout=0.02)
        except asyncio.TimeoutError:
            pcm = np.zeros(FRAME_SIZE, dtype=np.int16)

        pts = self._samples
        n = len(pcm)
        self._samples += n

        frame = av.AudioFrame(format="s16", layout="mono", samples=n)
        frame.planes[0].update(pcm.tobytes())
        frame.pts = pts
        frame.sample_rate = SAMPLE_RATE
        frame.time_base = self._time_base
        return frame
