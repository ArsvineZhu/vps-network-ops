#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) == 0 ]] || {
    echo "root required" >&2
    exit 1
}
[[ $(sysctl -n net.ipv4.ip_forward) == 1 ]] || {
    echo "ip_forward changed; stop for review" >&2
    exit 1
}
iptables -S ufw-user-forward >/dev/null
nft list chain inet mihomo_guard guard >/dev/null
if nft list table inet tcpfp_test >/dev/null 2>&1 || nft list table ip tcpfp_test_nat >/dev/null 2>&1; then
    echo "Fingerprint network table already exists" >&2
    exit 1
fi
STAGE=/etc/tcpfp
INTEGRATION=/usr/local/lib/tcpfp
WAN=$(python3 -c 'import json; print(json.load(open("/etc/tcpfp/plan.json"))["wan"])')
WINDOWS_ENGINE=$(python3 "$INTEGRATION/engines.py" windows)
IOS_ENGINE=$(python3 "$INTEGRATION/engines.py" ios)
python3 "$STAGE/preflight.py"
nft -c -f "$STAGE/host.nft"
ip netns add tcpfp-windows-test
ip link add tfp-win0 type veth peer name e0 netns tcpfp-windows-test
ip addr add 10.203.1.1/30 dev tfp-win0
ip link set tfp-win0 mtu 1500 up
ip -n tcpfp-windows-test link set lo up
ip -n tcpfp-windows-test addr add 10.203.1.2/30 dev e0
ip -n tcpfp-windows-test link set e0 mtu 1500 up
ip -n tcpfp-windows-test route add default via 10.203.1.1 dev e0
ip netns exec tcpfp-windows-test sysctl -qw net.ipv4.tcp_timestamps=0
ip netns exec tcpfp-windows-test sysctl -qw net.ipv4.ip_default_ttl=129
ip netns exec tcpfp-windows-test sysctl -qw 'net.ipv4.tcp_rmem=4096 131072 8388608'
ip netns exec tcpfp-windows-test sysctl -qw net.ipv4.tcp_ecn=0
ip netns exec tcpfp-windows-test sysctl -qw net.ipv4.tcp_congestion_control=bbr
ip netns exec tcpfp-windows-test sysctl -qw net.ipv4.tcp_fastopen=0
ip netns exec tcpfp-windows-test sysctl -qw net.ipv4.tcp_sack=1
ip netns exec tcpfp-windows-test sysctl -qw net.ipv4.tcp_window_scaling=1
ip netns exec tcpfp-windows-test sysctl -qw net.ipv4.tcp_syn_retries=3
ip netns exec tcpfp-windows-test nft -c -f "$STAGE/windows.nft"
ip netns exec tcpfp-windows-test nft -f "$STAGE/windows.nft"
if [[ $WINDOWS_ENGINE == tc ]]; then
    ip netns exec tcpfp-windows-test tc qdisc add dev e0 clsact
    ip netns exec tcpfp-windows-test tc filter add dev e0 egress chain 0 protocol ip pref 49152 handle 1 bpf da obj "$INTEGRATION/ebpf/syn_rewrite.o" sec tc_win
fi
ip netns add tcpfp-ios-test
ip link add tfp-ios0 type veth peer name e0 netns tcpfp-ios-test
ip addr add 10.203.2.1/30 dev tfp-ios0
ip link set tfp-ios0 mtu 1500 up
ip -n tcpfp-ios-test link set lo up
ip -n tcpfp-ios-test addr add 10.203.2.2/30 dev e0
ip -n tcpfp-ios-test link set e0 mtu 1500 up
ip -n tcpfp-ios-test route add default via 10.203.2.1 dev e0
ip netns exec tcpfp-ios-test sysctl -qw net.ipv4.tcp_timestamps=1
ip netns exec tcpfp-ios-test sysctl -qw net.ipv4.ip_default_ttl=65
ip netns exec tcpfp-ios-test sysctl -qw 'net.ipv4.tcp_rmem=4096 262144 2097152'
ip netns exec tcpfp-ios-test sysctl -qw net.ipv4.tcp_ecn=0
ip netns exec tcpfp-ios-test sysctl -qw net.ipv4.tcp_congestion_control=bbr
ip netns exec tcpfp-ios-test sysctl -qw net.ipv4.tcp_fastopen=0
ip netns exec tcpfp-ios-test sysctl -qw net.ipv4.tcp_sack=1
ip netns exec tcpfp-ios-test sysctl -qw net.ipv4.tcp_window_scaling=1
ip netns exec tcpfp-ios-test sysctl -qw net.ipv4.tcp_syn_retries=3
ip netns exec tcpfp-ios-test nft -c -f "$STAGE/ios.nft"
ip netns exec tcpfp-ios-test nft -f "$STAGE/ios.nft"
if [[ $IOS_ENGINE == tc ]]; then
    ip netns exec tcpfp-ios-test tc qdisc add dev e0 clsact
    ip netns exec tcpfp-ios-test tc filter add dev e0 egress chain 0 protocol ip pref 49152 handle 1 bpf da obj "$INTEGRATION/ebpf/syn_rewrite.o" sec tc_ios
fi
nft -f "$STAGE/host.nft"
iptables -I ufw-user-forward 1 -i tfp-win0 -o "$WAN" -s 10.203.1.2/32 -p tcp -m comment --comment tcpfp-test:windows:tcp -j ACCEPT
iptables -I ufw-user-forward 1 -i tfp-win0 -o "$WAN" -s 10.203.1.2/32 -p udp -d 1.1.1.1/32 --dport 53 -m comment --comment tcpfp-test:windows:dns -j ACCEPT
iptables -I ufw-user-forward 1 -i tfp-ios0 -o "$WAN" -s 10.203.2.2/32 -p tcp -m comment --comment tcpfp-test:ios:tcp -j ACCEPT
iptables -I ufw-user-forward 1 -i tfp-ios0 -o "$WAN" -s 10.203.2.2/32 -p udp -d 1.1.1.1/32 --dport 53 -m comment --comment tcpfp-test:ios:dns -j ACCEPT
echo "Fingerprint network is ready."
