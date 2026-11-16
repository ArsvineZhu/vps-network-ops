import json
import os
import shutil
import subprocess

import pytest

from vps_ops import forwarding


@pytest.mark.skipif(
    os.name != "posix" or os.geteuid() != 0, reason="Isolated Linux network namespace"
)
def test_owned_firewall_is_valid_idempotent_and_preserves_unrelated_rules():
    config = {"mode": "both", "features": {"fingerprint": True, "rtt": True}, "wan": "eth0"}
    guard, nat = forwarding.wireguard_rules(
        config, [{"address": "10.220.0.2"}, {"address": "10.220.128.2"}]
    )
    capture = forwarding.fingerprint_rules(config)
    # Privileged rules exist exclusively in this process's disposable net namespace.
    script = """
import json,subprocess,sys
from vps_ops import forwarding
payload=json.loads(sys.argv[1])
forwarding.command("nft","add","table","inet","unrelated")
for _ in range(2):
 for family,name,rules in payload:
  forwarding.replace_table(family,name,rules)
state=json.loads(forwarding.command("nft","-j","list","ruleset"))
assert any(x.get("table",{}).get("name")=="unrelated" for x in state["nftables"])
for _ in range(2):
 for family,name,_ in payload:
  forwarding.remove_table(family,name)
assert forwarding.table_exists("inet","unrelated")
"""
    subprocess.run(
        [
            "unshare",
            "-n",
            "--",
            "python3",
            "-c",
            script,
            json.dumps(
                [
                    ["inet", "vps_wireguard_guard", guard],
                    ["ip", "vps_wireguard_nat", nat],
                    ["ip", "vps_fingerprint_forward", capture],
                ]
            ),
        ],
        check=True,
    )


def test_forwarding_capture_only_enables_requested_paths():
    wg = forwarding.fingerprint_rules({"mode": "mihomo", "features": {"rtt": True}, "wan": "eth0"})
    assert "ip saddr 10.220.0.0/17 ip ttl set 128" in wg
    assert "ip saddr 10.220.128.0/17 ip ttl set 64" in wg
    assert "tailscale0" not in wg
    assert "10.221." not in wg
    native = forwarding.fingerprint_rules(
        {"mode": "tailscale", "features": {"fingerprint": True}, "wan": "eth0"}
    )
    assert "timestamp exists queue num 4948" in native
    assert "timestamp missing queue num 4947" in native
    assert "vps-ops" not in native


@pytest.mark.skipif(os.name != "posix" or os.geteuid() != 0, reason="POSIX group ownership")
def test_atomic_snapshot_writer_sets_group_before_publication(tmp_path, monkeypatch):
    from vps_ops import files

    target = tmp_path / "snapshot.json"
    replace = files.os.replace
    published = []

    def publish(source, destination):
        info = os.stat(source)
        published.append((info.st_gid, info.st_mode & 0o777))
        replace(source, destination)

    monkeypatch.setattr(files.os, "replace", publish)
    files.save(target, {"counter": 1}, 0o640, group=65534)
    assert published == [(65534, 0o640)]
    os.chown(target, -1, 0)
    target.chmod(0o600)
    files.save(target, {"counter": 1}, 0o640, group=65534)
    assert target.stat().st_gid == 65534
    assert target.stat().st_mode & 0o777 == 0o640
    assert len(published) == 1


@pytest.mark.skipif(os.name != "posix" or os.geteuid() != 0, reason="Isolated Linux forwarding")
def test_wireguard_guard_allows_established_reply_and_blocks_private_and_host():
    # Three isolated network namespaces exercise real conntrack state evaluation.
    script = r"""import os,socket,subprocess,sys,time
from vps_ops import forwarding
router_namespace=os.stat('/proc/self/ns/net').st_ino
peers=[]
server=None
local_server=None

def run(*args):
 return subprocess.run(args,check=True,text=True,capture_output=True).stdout

def inside(peer,*args):
 return ['nsenter','-t',str(peer.pid),'-n',*args]

try:
 for _ in range(2):
  peer=subprocess.Popen(['unshare','-n','sleep','30'])
  peers.append(peer)
  end=time.monotonic()+3
  while os.stat(f'/proc/{peer.pid}/ns/net').st_ino==router_namespace:
   if time.monotonic()>end:raise RuntimeError('Namespace startup timed out')
   time.sleep(.01)
 client,remote=peers
 for local,other,peer,address,gateway in [
  ('vps-ops','client0',client,'10.220.0.2/24','10.220.0.1'),
  ('eth0','remote0',remote,'1.1.1.1/24','1.1.1.254')]:
  run('ip','link','add',local,'type','veth','peer','name',other)
  run('ip','link','set',other,'netns',str(peer.pid))
  run('ip','address','add',gateway+'/24','dev',local)
  run('ip','link','set',local,'up')
  run(*inside(peer,'ip','address','add',address,'dev',other))
  run(*inside(peer,'ip','link','set',other,'up'))
  run(*inside(peer,'ip','link','set','lo','up'))
  run(*inside(peer,'ip','route','add','default','via',gateway))
 run('ip','address','add','172.20.0.1/24','dev','eth0')
 run(*inside(remote,'ip','address','add','172.20.0.2/24','dev','remote0'))
 run('sysctl','-qw','net.ipv4.ip_forward=1')
 guard,_=forwarding.wireguard_rules({'mode':'mihomo','features':{'rtt':True},'wan':'eth0'}, [{'address':'10.220.0.2'}])
 forwarding.replace_table('inet','vps_wireguard_guard',guard)
 echo="import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.bind(('0.0.0.0',9999));print('ready',flush=True);\nwhile True:\n data,address=s.recvfrom(1024);s.sendto(data,address)"
 server=subprocess.Popen(inside(remote,'python3','-u','-c',echo),stdout=subprocess.PIPE,text=True)
 assert server.stdout.readline().strip()=='ready'
 local_server=subprocess.Popen(['python3','-u','-c',echo],stdout=subprocess.PIPE,text=True)
 assert local_server.stdout.readline().strip()=='ready'
 request="import socket,sys;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(1);s.sendto(b'reply-contract',(sys.argv[1],9999));print(s.recv(1024).decode())"
 assert run(*inside(client,'python3','-c',request,'1.1.1.1')).strip()=='reply-contract'
 for blocked in ('172.20.0.2','10.220.0.1'):
  result=subprocess.run(inside(client,'python3','-c',request,blocked),capture_output=True)
  assert result.returncode!=0 and b'TimeoutError' in result.stderr, result
 empty,_=forwarding.wireguard_rules({'mode':'mihomo','features':{'rtt':True},'wan':'eth0'}, [])
 forwarding.replace_table('inet','vps_wireguard_guard',empty)
 denied=subprocess.run(inside(client,'python3','-c',request,'1.1.1.1'),capture_output=True)
 assert denied.returncode!=0 and b'TimeoutError' in denied.stderr
finally:
 for process in (server,local_server):
  if process is not None:
   process.terminate();process.wait(timeout=3)
 for peer in peers:
  peer.terminate();peer.wait(timeout=3)
"""
    subprocess.run(["unshare", "-n", "--", "python3", "-c", script], check=True, timeout=20)


@pytest.mark.skipif(
    os.name != "posix" or os.geteuid() != 0 or shutil.which("iptables") is None,
    reason="Linux namespace lifecycle requires root and iptables",
)
def test_local_fingerprint_cleanup_removes_owned_resources_idempotently():
    script = r"""import json,subprocess
from pathlib import Path
from vps_ops import forwarding

def run(*args):
 return subprocess.run(args,check=True,text=True,capture_output=True).stdout

run('mount','--make-rprivate','/')
Path('/run/netns').mkdir(exist_ok=True)
run('mount','-t','tmpfs','tmpfs','/run/netns')
run('iptables','-N','ufw-user-forward')
run('nft','add','table','inet','tcpfp_test')
run('nft','add','table','ip','tcpfp_test_nat')
run('nft','add','table','inet','unrelated')
for name,link in [('tcpfp-windows-test','tfp-win0'),('tcpfp-ios-test','tfp-ios0')]:
 run('ip','netns','add',name)
 run('ip','link','add',link,'type','veth','peer','name','e0','netns',name)
 run('iptables','-A','ufw-user-forward','-i',link,'-m','comment','--comment','tcpfp-test:'+name,'-j','ACCEPT')
for _ in range(2):
 forwarding.local_stop()
 assert run('ip','netns','list').strip()==''
 assert not any(x['ifname'] in {'tfp-win0','tfp-ios0'} for x in json.loads(run('ip','-j','link','show')))
 assert forwarding.table_exists('inet','unrelated')
 assert not forwarding.table_exists('inet','tcpfp_test')
 assert not forwarding.table_exists('ip','tcpfp_test_nat')
 assert 'tcpfp-test:' not in run('iptables','-S','ufw-user-forward')
"""
    subprocess.run(["unshare", "-nm", "--", "python3", "-c", script], check=True, timeout=20)


def test_atomic_writer_preserves_utf8_and_corrects_crlf(tmp_path):
    from vps_ops.files import save

    path = tmp_path / "node.yaml"
    path.write_bytes("name: 東京\r\n".encode())
    save(path, "name: 東京\n")
    assert path.read_bytes() == "name: 東京\n".encode()
