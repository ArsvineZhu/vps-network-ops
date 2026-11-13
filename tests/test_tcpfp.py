import json

import engines
import pytest
import render_assets
import syn_capture


def test_network_configuration_uses_the_selected_address_and_interface(tmp_path):
    output = tmp_path / "network"
    render_assets.render("203.0.113.17", "eth0", output)
    host = (output / "host.nft").read_text(encoding="utf-8")
    assert "203.0.113.17/32" in host
    assert 'oifname "eth0"' in host
    assert json.loads((output / "plan.json").read_text())["wan"] == "eth0"


def test_fingerprint_engines_are_exclusive(tmp_path):
    path = tmp_path / "engines.json"
    with pytest.raises(FileNotFoundError):
        engines.load(path)
    config = {"windows": "nfqueue", "ios": "tc"}
    path.write_text(json.dumps(config), encoding="utf-8")
    assert engines.load(path) == config
    bpf = [{"kind": "bpf", "options": {"bpf_name": "syn_rewrite.o:[tc_win]"}}]
    table = [{"table": {"family": "ip", "name": "vps_syn"}}]
    engines.verify_runtime("tc", "tc_win", bpf, [])
    with pytest.raises(ValueError):
        engines.verify_runtime("tc", "tc_win", bpf, table)
    with pytest.raises(ValueError):
        engines.verify_runtime("nfqueue", "tc_win", bpf, [])


@pytest.mark.parametrize("flags", [["syn", "ack"], {"|": ["syn", "ack"]}])
def test_capture_rule_accepts_nft_json_and_rejects_extra_objects(monkeypatch, flags):
    table = {"family": "ip", "name": "vps_syn", "handle": 6}
    chain = {
        "family": "ip",
        "table": "vps_syn",
        "name": "output",
        "type": "filter",
        "hook": "postrouting",
        "prio": -150,
        "policy": "accept",
    }
    rules = [
        {"match": {"op": "==", "left": {"meta": {"key": "oifname"}}, "right": "e0"}},
        {
            "match": {
                "op": "==",
                "left": {"&": [{"payload": {"protocol": "tcp", "field": "flags"}}, flags]},
                "right": "syn",
            }
        },
        {"queue": {"num": 4949}},
    ]
    listing = {
        "nftables": [
            {"table": table},
            {"chain": chain},
            {"rule": {"chain": "output", "expr": rules}},
        ]
    }
    monkeypatch.setattr(syn_capture, "nft", lambda *_args, **_kwargs: json.dumps(listing))
    config = syn_capture.Capture("e0", 4949, "strict")
    syn_capture.verify_rule(config)
    listing["nftables"].append({"set": {"name": "foreign"}})
    with pytest.raises(ValueError):
        syn_capture.verify_rule(config)
