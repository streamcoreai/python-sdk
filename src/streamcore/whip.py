from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

import aiohttp


@dataclass
class WhipResult:
    answer_sdp: str
    session_url: str


async def whip_offer(endpoint: str, offer_sdp: str, token: str = "") -> WhipResult:
    """Perform a WHIP signaling exchange per RFC 9725 §4.2.

    POST an SDP offer, receive a 201 Created with SDP answer and Location header.
    """
    headers: dict[str, str] = {"Content-Type": "application/sdp"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with aiohttp.ClientSession() as session:
        async with session.post(
            endpoint,
            data=offer_sdp,
            headers=headers,
        ) as resp:
            if resp.status != 201:
                body = await resp.text()
                raise RuntimeError(f"WHIP: unexpected status {resp.status}: {body}")

            answer_sdp = await resp.text()

            location = resp.headers.get("Location", "")
            session_url = location
            if location and not location.startswith("http"):
                parsed = urlparse(endpoint)
                session_url = urlunparse(
                    (parsed.scheme, parsed.netloc, location, "", "", "")
                )

            return WhipResult(answer_sdp=answer_sdp, session_url=session_url)


async def whip_delete(session_url: str, token: str = "") -> None:
    """Terminate a WHIP session per RFC 9725 §4.2.

    Send HTTP DELETE to the WHIP session URL. Best-effort; errors are ignored.
    """
    if not session_url:
        return
    try:
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.delete(session_url, headers=headers):
                pass
    except Exception:
        pass
