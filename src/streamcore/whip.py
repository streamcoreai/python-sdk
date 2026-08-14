from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

import aiohttp

from .icerestart import ICE_FRAGMENT_CONTENT_TYPE

#: Carries the caller identity when there is no token endpoint to sign one into
#: a claim. For server-side clients, not browsers.
RESOURCE_ID_HEADER = "X-StreamCore-Resource-Id"


@dataclass
class WhipResult:
    answer_sdp: str
    session_url: str
    #: ETag identifying the ICE session (RFC 9725 §4.3.1); required to PATCH it.
    etag: str = ""
    #: Single-use credential for reattaching a later redial to this
    #: conversation. Empty when the server cannot resume (realtime sessions).
    resume_token: str = ""
    #: "new", "resumed", or "expired". Anything but "resumed" on a redial means
    #: the agent has no memory of the earlier conversation.
    resume_status: str = ""


@dataclass
class WhipRestartResult:
    #: The server's sdpfrag, to fold into the stored remote description.
    fragment: str
    #: The rotated tag identifying the new ICE session.
    etag: str


class WhipRestartError(RuntimeError):
    """Raised when an ICE restart PATCH is rejected."""

    def __init__(self, status: int, body: str, current_etag: str = "") -> None:
        super().__init__(f"WHIP: ICE restart failed ({status}): {body}")
        self.status = status
        self.body = body
        #: The tag the server reported as current, present on a 412.
        self.current_etag = current_etag

    @property
    def retryable(self) -> bool:
        """Whether another attempt against the same session could still work.

        A 404 means the session was reaped, 409 that it has no peer to restart,
        and 405 that the server declines restarts entirely — only a redial
        recovers from those.
        """
        return self.status not in (404, 409, 405)


async def whip_offer(
    endpoint: str,
    offer_sdp: str,
    token: str = "",
    resume_token: str = "",
    resource_id: str = "",
) -> WhipResult:
    """Perform a WHIP signaling exchange per RFC 9725 §4.2.

    POST an SDP offer, receive a 201 Created with SDP answer and Location header.

    ``resume_token`` is a StreamCore extension: it asks the server to reattach
    this new transport to the conversation a previous connection was having,
    rather than starting a fresh one. Check ``resume_status`` on the result —
    a token the server no longer recognises still yields a working call, but
    one whose agent remembers nothing.

    ``resource_id`` goes in a header, and the server ignores it whenever the
    token already carries a claim.
    """
    headers: dict[str, str] = {"Content-Type": "application/sdp"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if resource_id:
        headers[RESOURCE_ID_HEADER] = resource_id

    params = {"resume": resume_token} if resume_token else None

    async with aiohttp.ClientSession() as session:
        async with session.post(
            endpoint,
            data=offer_sdp,
            headers=headers,
            params=params,
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

            return WhipResult(
                answer_sdp=answer_sdp,
                session_url=session_url,
                etag=resp.headers.get("ETag", ""),
                resume_token=resp.headers.get("X-Resume-Token", ""),
                resume_status=resp.headers.get("X-Resume-Status", ""),
            )


async def whip_restart_ice(
    session_url: str,
    fragment: str,
    etag: str = "",
    token: str = "",
) -> WhipRestartResult:
    """Send an ICE restart to the session URL per RFC 9725 §4.4.2.

    ``etag`` is sent as ``If-Match`` so a restart racing another one is
    rejected rather than applied to a generation that no longer exists.

    Note that aiortc cannot produce an ICE restart offer, so this is for
    callers driving another WebRTC stack — see :mod:`streamcore.icerestart`.
    """
    headers: dict[str, str] = {"Content-Type": ICE_FRAGMENT_CONTENT_TYPE}
    if etag:
        headers["If-Match"] = etag
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with aiohttp.ClientSession() as session:
        async with session.patch(session_url, data=fragment, headers=headers) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise WhipRestartError(
                    resp.status, body, resp.headers.get("ETag", "")
                )
            return WhipRestartResult(
                fragment=body,
                etag=resp.headers.get("ETag", "") or etag,
            )


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
