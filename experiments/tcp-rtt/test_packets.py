import socket

import dpkt
import pytest
from packets import handshakes


@pytest.mark.parametrize("data_first", (False, True))
def test_report_identifies_the_packet_completing_the_handshake(tmp_path, data_first):
    capture = tmp_path / "handshake.pcap"
    client, server = map(socket.inet_aton, ("10.231.2.1", "10.231.2.2"))

    def frame(reverse, flags, seq, ack, payload=b""):
        tcp = dpkt.tcp.TCP(
            sport=4433 if reverse else 50000,
            dport=50000 if reverse else 4433,
            flags=flags,
            seq=seq,
            ack=ack,
            data=payload,
        )
        ip = dpkt.ip.IP(
            src=server if reverse else client, dst=client if reverse else server, p=6, data=tcp
        )
        ip.len = len(ip)
        return bytes(dpkt.ethernet.Ethernet(type=0x800, data=ip))

    with capture.open("wb") as output:
        writer = dpkt.pcap.Writer(output)
        writer.writepkt(frame(False, 2, 100, 0), 1)
        writer.writepkt(frame(True, 18, 200, 101), 1.025)
        if data_first:
            writer.writepkt(frame(False, 24, 101, 201, b"TLS"), 1.075)
        writer.writepkt(frame(False, 16, 101, 201), 1.125 if data_first else 1.075)

    rows = handshakes(capture)
    assert len(rows) == 1
    assert rows[0]["synack_to_final_ack_ms"] == pytest.approx(50)
    assert rows[0]["data_overtook_pure_ack"] is data_first
    assert rows[0]["final_ack_payload_bytes"] == (3 if data_first else 0)
