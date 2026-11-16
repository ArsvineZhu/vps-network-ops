"""Extract handshake ACK timing from the destination-side experiment capture."""

import argparse
import json
from pathlib import Path
from typing import Any, cast

import dpkt


def tcp_frames(path):
    with path.open("rb") as source:
        for stamp, frame in dpkt.pcap.Reader(source):
            packet = dpkt.ethernet.Ethernet(frame).data
            if isinstance(packet, dpkt.ip.IP) and isinstance(packet.data, dpkt.tcp.TCP):
                yield stamp, cast(Any, packet), cast(Any, packet.data)


def handshakes(path, port=4433):
    flows = {}
    for stamp, packet, tcp in tcp_frames(path):
        outbound = tcp.dport == port
        if not outbound and tcp.sport != port:
            continue
        key = (
            (packet.src, packet.dst, tcp.sport, tcp.dport)
            if outbound
            else (packet.dst, packet.src, tcp.dport, tcp.sport)
        )
        if outbound and tcp.flags & (dpkt.tcp.TH_SYN | dpkt.tcp.TH_ACK) == dpkt.tcp.TH_SYN:
            previous = flows.get(key)
            if previous is None or previous["client_seq"] != tcp.seq:
                flows[key] = {
                    "client_seq": tcp.seq,
                    "syn_time": stamp,
                    "ttl": packet.ttl,
                    "options": [kind for kind, _ in dpkt.tcp.parse_opts(tcp.opts)],
                }
        flow = flows.get(key)
        if flow is None:
            continue
        if not outbound and tcp.flags & 0x12 == 0x12:
            flow.setdefault("synack_time", stamp)
            flow["server_seq"] = tcp.seq
        if outbound and tcp.flags & dpkt.tcp.TH_ACK and "synack_time" in flow:
            if tcp.ack == (flow["server_seq"] + 1) & 0xFFFFFFFF:
                flow.setdefault("final_ack_time", stamp)
                flow.setdefault("final_ack_payload_bytes", len(tcp.data))
                if not tcp.data:
                    flow.setdefault("pure_ack_time", stamp)
                else:
                    flow.setdefault("data_ack_time", stamp)
    result = []
    for (_, _, port, _), flow in flows.items():
        if "final_ack_time" not in flow:
            continue
        base = flow["synack_time"]
        result.append(
            {
                "client_port": port,
                "client_ttl_at_capture": flow["ttl"],
                "syn_options": flow["options"],
                "synack_to_final_ack_ms": (flow["final_ack_time"] - base) * 1000,
                "final_ack_payload_bytes": flow["final_ack_payload_bytes"],
                "synack_to_pure_ack_ms": (flow["pure_ack_time"] - base) * 1000
                if "pure_ack_time" in flow
                else None,
                "data_overtook_pure_ack": "data_ack_time" in flow
                and ("pure_ack_time" not in flow or flow["data_ack_time"] < flow["pure_ack_time"]),
            }
        )
    return result


def acknowledgements(path, port=4433):
    highest = {}
    result = {"pure_bytes": 0, "data_bytes": 0, "pure_packets": 0, "data_packets": 0}
    for _stamp, ip, tcp in tcp_frames(path):
        if tcp.dport != port:
            continue
        key = (ip.src, ip.dst, tcp.sport, tcp.dport)
        if tcp.flags & 0x12 == 2:
            highest.pop(key, None)
            continue
        if not tcp.flags & dpkt.tcp.TH_ACK:
            continue
        if key not in highest:
            highest[key] = tcp.ack
            continue
        advance = (tcp.ack - highest[key]) & 0xFFFFFFFF
        if 0 < advance < 0x80000000:
            kind = "data" if tcp.data else "pure"
            result[kind + "_bytes"] += advance
            result[kind + "_packets"] += 1
            highest[key] = tcp.ack
    total = result["pure_bytes"] + result["data_bytes"]
    return dict(result, data_fraction=result["data_bytes"] / total if total else None)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--port", type=int, default=4433)
    parser.add_argument("--acks", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            acknowledgements(args.capture, args.port)
            if args.acks
            else handshakes(args.capture, args.port),
            indent=2,
        )
    )
