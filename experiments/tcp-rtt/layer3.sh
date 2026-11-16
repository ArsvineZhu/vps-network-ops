#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 || $EUID -ne 0 ]]; then
    echo "Usage (root): layer3.sh TAILSCALE_BINARY_DIRECTORY UPLINK_INTERFACE" >&2
    exit 2
fi
binary_dir=$(realpath "$1")
uplink=$2
namespace=rtt-exit
host_link=rtt-exit-host
state_dir=$(mktemp -d /tmp/rtt-exit.XXXXXXXX)
previous_forwarding=$(sysctl -n net.ipv4.ip_forward)
created_namespace=false
created_table=false
changed_forwarding=false

cleanup() {
    set +e
    if $created_namespace; then
        timeout 5 "$binary_dir/tailscale" --socket="$state_dir/control.sock" logout >/dev/null 2>&1
        for pid in $(ip netns pids "$namespace"); do
            kill "$pid"
        done
        if [[ -n ${daemon_pid:-} ]]; then
            wait "$daemon_pid" 2>/dev/null
        fi
        ip netns delete "$namespace"
        ip link delete "$host_link" 2>/dev/null
        rm -f "/etc/netns/$namespace/resolv.conf"
        rmdir "/etc/netns/$namespace" 2>/dev/null
    fi
    if $created_table; then
        nft delete table ip rtt_exit
    fi
    if $changed_forwarding; then
        sysctl -qw "net.ipv4.ip_forward=$previous_forwarding"
    fi
    rm -rf -- "$state_dir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if ip netns list | cut -d' ' -f1 | grep -qx "$namespace" || [[ -e /etc/netns/$namespace ]]; then
    echo "Experiment namespace or resolver directory already exists" >&2
    exit 1
fi
if ip link show "$host_link" >/dev/null 2>&1 || nft list table ip rtt_exit >/dev/null 2>&1; then
    echo "Experiment host interface or NAT table already exists" >&2
    exit 1
fi
ip link show "$uplink" >/dev/null
test -x "$binary_dir/tailscale"
test -x "$binary_dir/tailscaled"
ip netns add "$namespace"
created_namespace=true
ip link add "$host_link" type veth peer name rtt-exit0 netns "$namespace"
ip addr add 10.233.0.1/30 dev "$host_link"
ip link set "$host_link" up
ip netns exec "$namespace" ip addr add 10.233.0.2/30 dev rtt-exit0
ip netns exec "$namespace" ip link set rtt-exit0 up
ip netns exec "$namespace" ip link set lo up
ip netns exec "$namespace" ip route add default via 10.233.0.1
mkdir -p "/etc/netns/$namespace"
printf 'nameserver 1.1.1.1\n' >"/etc/netns/$namespace/resolv.conf"
sysctl -qw net.ipv4.ip_forward=1
changed_forwarding=true
nft add table ip rtt_exit
created_table=true
nft 'add chain ip rtt_exit postrouting { type nat hook postrouting priority srcnat; }'
nft add rule ip rtt_exit postrouting ip saddr 10.233.0.0/30 oifname "$uplink" masquerade
printf 'Namespace: %s\nSocket: %s/control.sock\n' "$namespace" "$state_dir"
ip netns exec "$namespace" "$binary_dir/tailscaled" --state=mem: \
    --statedir="$state_dir" --socket="$state_dir/control.sock" --tun=rtt-exit-tun &
daemon_pid=$!
wait "$daemon_pid"
