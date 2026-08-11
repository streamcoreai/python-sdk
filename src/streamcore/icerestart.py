"""ICE restart support (RFC 9725 §4.4, RFC 8840).

When the local address changes — a machine moving networks, a VPN toggle, a NAT
rebind that does not recover — the gathered candidates are dead and the
connection cannot heal on its own. Re-POSTing an offer would allocate a new
session on the server, losing the conversation history and replaying the
greeting. An ICE restart instead swaps only the ICE generation on the existing
session, so nothing above the transport notices.

.. warning::
   The SDK does **not** drive this automatically, because aiortc has no ICE
   restart primitive: ``RTCPeerConnection.createOffer()`` takes no options,
   aioice fixes its ICE credentials at construction, and aiortc explicitly has
   no ``disconnected`` connection state to trigger on (it goes straight from
   ``connected`` to ``failed``). Performing a restart would mean rebuilding the
   ICE layer under a live DTLS session, which aiortc cannot do.

   These helpers are the wire format, tested and ready, for callers driving
   another WebRTC stack — and for the day aiortc gains the primitive. The
   TypeScript, React Native, Go, and Rust SDKs do reconnect automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Media type of an ICE restart body.
ICE_FRAGMENT_CONTENT_TYPE = "application/trickle-ice-sdpfrag"


@dataclass
class IceDetails:
    """ICE credentials and candidates read out of an SDP or fragment."""

    ufrag: str = ""
    pwd: str = ""
    candidates: list[str] = field(default_factory=list)


def _split_sdp_lines(sdp: str) -> list[str]:
    """Split an SDP or fragment into lines, tolerating LF-only bodies."""
    return [line.rstrip("\r") for line in sdp.split("\n") if line.rstrip("\r")]


def parse_ice_details(sdp: str) -> IceDetails:
    """Read the ICE credentials and candidates out of an SDP or fragment.

    Credentials may sit at session or media level; the first of each wins,
    which is what a bundled description means anyway.
    """
    details = IceDetails()

    for line in _split_sdp_lines(sdp):
        if line.startswith("a=ice-ufrag:"):
            if not details.ufrag:
                details.ufrag = line[len("a=ice-ufrag:") :]
        elif line.startswith("a=ice-pwd:"):
            if not details.pwd:
                details.pwd = line[len("a=ice-pwd:") :]
        elif line.startswith("a=candidate:"):
            details.candidates.append(line[len("a=candidate:") :])

    return details


def ice_fragment_from_sdp(local_sdp: str) -> str:
    """Render a local offer as the sdpfrag to PATCH.

    The credentials, then the bundle-master m-line with its mid and candidates.
    Shaped after the request example in RFC 9725 §4.4.2.
    """
    ufrag = ""
    pwd = ""
    m_line = ""
    mid = ""
    candidates: list[str] = []
    media_index = -1

    for line in _split_sdp_lines(local_sdp):
        if line.startswith("m="):
            media_index += 1
            if media_index == 0:
                m_line = line
            continue
        # Session-level attributes and the first media section's are both
        # usable; later sections are bundled onto the first.
        if media_index > 0:
            continue

        if line.startswith("a=ice-ufrag:"):
            if not ufrag:
                ufrag = line[len("a=ice-ufrag:") :]
        elif line.startswith("a=ice-pwd:"):
            if not pwd:
                pwd = line[len("a=ice-pwd:") :]
        elif line.startswith("a=mid:"):
            if not mid:
                mid = line[len("a=mid:") :]
        elif line.startswith("a=candidate:"):
            candidates.append(line[len("a=candidate:") :])

    out: list[str] = []
    if ufrag:
        out.append(f"a=ice-ufrag:{ufrag}")
    if pwd:
        out.append(f"a=ice-pwd:{pwd}")
    if m_line:
        out.append(m_line)
    if mid:
        out.append(f"a=mid:{mid}")
    out.extend(f"a=candidate:{c}" for c in candidates)
    out.append("a=end-of-candidates")

    return "\r\n".join(out) + "\r\n"


def apply_ice_fragment(remote_sdp: str, fragment: str) -> str | None:
    """Fold the server's reply fragment into the answer already held.

    Produces a full SDP that ``setRemoteDescription`` accepts. Only the ICE
    generation changes: credentials are replaced wherever they appear, stale
    candidates are dropped, and the new ones are inserted into the first media
    section. Everything else — m-lines, payload types, the DTLS fingerprint,
    SSRCs — is carried over verbatim, because a restart is not meant to
    renegotiate any of it.

    Returns ``None`` if the fragment carries no credentials, which would mean
    it is not a restart reply at all.
    """
    details = parse_ice_details(fragment)
    if not details.ufrag or not details.pwd:
        return None

    candidate_lines = [f"a=candidate:{c}" for c in details.candidates]
    if candidate_lines:
        candidate_lines.append("a=end-of-candidates")

    out: list[str] = []
    media_index = -1
    inserted = False

    for line in _split_sdp_lines(remote_sdp):
        if line.startswith("m="):
            # Leaving the first media section — the new candidates belong at
            # its end, after the attributes it already carries.
            if media_index == 0 and not inserted:
                inserted = True
                out.extend(candidate_lines)
            media_index += 1
            out.append(line)
        elif line.startswith("o="):
            out.append(bump_sdp_origin(line))
        elif line.startswith("a=ice-ufrag:"):
            out.append(f"a=ice-ufrag:{details.ufrag}")
        elif line.startswith("a=ice-pwd:"):
            out.append(f"a=ice-pwd:{details.pwd}")
        elif line.startswith("a=candidate:") or line == "a=end-of-candidates":
            pass  # Previous ICE generation — dropped.
        else:
            out.append(line)

    if not inserted:
        out.extend(candidate_lines)

    return "\r\n".join(out) + "\r\n"


def bump_sdp_origin(line: str) -> str:
    """Increment the session version in an ``o=`` line.

    This is how JSEP marks a description as a new revision of the same session.
    """
    fields = line[len("o=") :].split() if line.startswith("o=") else line.split()
    if len(fields) < 6:
        return line
    try:
        version = int(fields[2])
    except ValueError:
        return line
    fields[2] = str(version + 1)
    return "o=" + " ".join(fields)
