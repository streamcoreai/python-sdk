from streamcore.icerestart import (
    apply_ice_fragment,
    bump_sdp_origin,
    ice_fragment_from_sdp,
    parse_ice_details,
)

REMOTE_ANSWER = (
    "v=0\r\n"
    "o=- 4611731400430051336 2 IN IP4 127.0.0.1\r\n"
    "s=-\r\n"
    "t=0 0\r\n"
    "a=group:BUNDLE 0 1\r\n"
    "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
    "c=IN IP4 0.0.0.0\r\n"
    "a=mid:0\r\n"
    "a=ice-ufrag:oldU\r\n"
    "a=ice-pwd:oldPassword0000000000\r\n"
    "a=fingerprint:sha-256 AA:BB:CC\r\n"
    "a=candidate:1 1 udp 2130706431 192.0.2.10 41000 typ host\r\n"
    "a=end-of-candidates\r\n"
    "a=rtpmap:111 opus/48000/2\r\n"
    "a=ssrc:12345 cname:stream\r\n"
    "m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n"
    "a=mid:1\r\n"
    "a=ice-ufrag:oldU\r\n"
    "a=ice-pwd:oldPassword0000000000\r\n"
)

SERVER_FRAGMENT = (
    "a=ice-ufrag:newU\r\n"
    "a=ice-pwd:newPassword111111111\r\n"
    "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
    "a=mid:0\r\n"
    "a=candidate:1 1 udp 2130706431 198.51.100.1 39132 typ host\r\n"
)


def test_parses_credentials_and_candidates():
    details = parse_ice_details(SERVER_FRAGMENT)
    assert details.ufrag == "newU"
    assert details.pwd == "newPassword111111111"
    assert len(details.candidates) == 1
    # The a=candidate: prefix is stripped, not kept.
    assert details.candidates[0].startswith("1 1 udp")


def test_parses_lf_only_bodies():
    details = parse_ice_details("a=ice-ufrag:newU\na=ice-pwd:pw\n")
    assert details.ufrag == "newU"
    assert details.pwd == "pw"


def test_builds_a_fragment_from_the_bundle_master_only():
    local = (
        "v=0\r\n"
        "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
        "a=mid:0\r\n"
        "a=ice-ufrag:localU\r\n"
        "a=ice-pwd:localPassword222222\r\n"
        "a=candidate:1 1 udp 2130706431 198.51.100.7 51000 typ host\r\n"
        "m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n"
        "a=mid:1\r\n"
        "a=candidate:9 1 udp 1 10.0.0.1 1 typ host\r\n"
    )
    frag = ice_fragment_from_sdp(local)

    assert "a=ice-ufrag:localU" in frag
    assert "a=ice-pwd:localPassword222222" in frag
    assert "m=audio 9 UDP/TLS/RTP/SAVPF 111" in frag
    assert "a=mid:0" in frag
    assert "198.51.100.7" in frag
    assert frag.endswith("a=end-of-candidates\r\n")
    # Bundled sections are not described.
    assert "m=application" not in frag
    assert "10.0.0.1" not in frag


def test_folds_a_fragment_into_the_stored_answer():
    applied = apply_ice_fragment(REMOTE_ANSWER, SERVER_FRAGMENT)
    assert applied is not None

    assert "oldU" not in applied
    assert "oldPassword0000000000" not in applied
    # Both bundled sections must agree on the new credentials.
    assert applied.count("a=ice-ufrag:newU") == 2
    assert applied.count("a=ice-pwd:newPassword111111111") == 2

    # Stale candidates go, new ones arrive.
    assert "192.0.2.10" not in applied
    assert "a=candidate:1 1 udp 2130706431 198.51.100.1 39132 typ host" in applied

    # Everything the transport is not responsible for survives verbatim.
    for must in (
        "a=mid:0",
        "a=mid:1",
        "a=ssrc:12345 cname:stream",
        "a=fingerprint:sha-256 AA:BB:CC",
        "a=rtpmap:111 opus/48000/2",
        "a=group:BUNDLE 0 1",
        "m=application 9 UDP/DTLS/SCTP webrtc-datachannel",
    ):
        assert must in applied, f"rewrite dropped {must}"

    # A new revision of the same session.
    assert "o=- 4611731400430051336 3 IN IP4 127.0.0.1" in applied


def test_candidates_land_in_the_first_media_section():
    applied = apply_ice_fragment(REMOTE_ANSWER, SERVER_FRAGMENT)
    audio = applied.index("m=audio")
    app = applied.index("m=application")
    candidate = applied.index("a=candidate:")
    assert audio < candidate < app


def test_rejects_a_fragment_without_credentials():
    trickle = (
        "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
        "a=candidate:1 1 udp 1 1.2.3.4 1 typ host\r\n"
    )
    assert apply_ice_fragment(REMOTE_ANSWER, trickle) is None


def test_leaves_a_malformed_origin_alone():
    assert bump_sdp_origin("o=- 123") == "o=- 123"
    assert (
        bump_sdp_origin("o=- 123 abc IN IP4 127.0.0.1")
        == "o=- 123 abc IN IP4 127.0.0.1"
    )
