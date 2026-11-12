#!/usr/bin/env bash
# Read-only local diagnostic. Output can contain IPs/hostnames: review before sharing.
case "${1-}" in
  -h|--help) echo "Usage: sudo bash vps_snapshot.sh — read-only local diagnostic; review IPs before sharing."; exit 0 ;;
  "") ;;
  *) echo "Unknown argument" >&2; exit 2 ;;
esac
set -u
export LC_ALL=C
section() { printf '\n=== %s ===\n' "$1"; }
run() { if command -v "$1" >/dev/null 2>&1; then "$@" 2>&1 || true; else printf 'Unavailable: %s\n' "$1"; fi; }
section 'OS and kernel'; run uname -sr; [ ! -r /etc/os-release ] || grep -E '^(ID|VERSION_ID)=' /etc/os-release
section 'Service state (not readiness)'; run systemctl show ssh.service mihomo.service mihomo-guard.service tailscaled.service -p Id -p ActiveState -p SubState -p UnitFileState -p MainPID -p After -p BindsTo
section 'Listening TCP/UDP sockets'; run ss -lntup
section 'Detailed TCP sockets (inspect v6only)'; run ss -lntpe
section 'Forwarding'; run sysctl net.ipv4.ip_forward net.ipv6.conf.all.forwarding
section 'IPv4 routes'; run ip -4 route show
section 'UFW'; run ufw status numbered
section 'Mihomo guard'; run nft -a list table inet mihomo_guard
section 'Package update/reboot indicators'; [ ! -e /var/run/reboot-required ] || cat /var/run/reboot-required
run apt list --upgradable
printf '\nNo settings changed; no remote probe or package refresh performed.\n'
