"""Pure rendering: no subprocesses, network, or writes."""
from __future__ import annotations
import ipaddress
import json
from config import BLOCKED, ROLES

ROOT = '/usr/local/lib/vps-network'
ETC = '/etc/vps-network'

def text_json(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + '\n'

def base():
    return {'mode': 'rule', 'log-level': 'warning', 'ipv6': False,
            'allow-lan': False, 'find-process-mode': 'off', 'tun': {'enable': False}}

def blocked_rules(site, no_resolve=False):
    tail = ',no-resolve' if no_resolve else ''
    return ['IP-CIDR6,::/0,REJECT', 'DOMAIN-SUFFIX,localhost,REJECT'] + [
        f'IP-CIDR,{x},REJECT{tail}' for x in (*BLOCKED, site['host']['public_ipv4'] + '/32')]

def frontend(site, secret):
    config = base()
    config['external-controller-unix'] = '/run/vps-mihomo/control.sock'
    config['dns'] = {'enable': True, 'ipv6': False, 'enhanced-mode': 'redir-host',
                     'use-hosts': False, 'use-system-hosts': False,
                     'nameserver': ['udp://' + site['host']['dns'] + ':53'],
                     'default-nameserver': [site['host']['dns']]}
    config['listeners'] = []
    for protocol, options in site['protocols'].items():
        if not options['enabled']:
            continue
        users = {d['id']: secret['devices'][d['id']][protocol]
                 for d in site['devices'] if protocol in d['protocols']}
        listener = {'name': protocol + '-in', 'type': protocol, 'listen': '0.0.0.0', 'port': options['port']}
        if protocol == 'vless':
            listener['users'] = [{'username': name, 'uuid': credential, 'flow': 'xtls-rprx-vision'}
                                 for name, credential in users.items()]
            listener['reality-config'] = {'dest': site['reality']['server_name'] + ':' + str(site['reality']['target_port']),
                'server-names': [site['reality']['server_name']], 'private-key': secret['reality']['private_key'],
                'short-id': [secret['reality']['short_id']]}
        else:
            listener.update({'users': users, 'certificate': ETC + '/tls/fullchain.pem', 'private-key': ETC + '/tls/privkey.pem'})
            if protocol == 'hysteria2':
                listener.update({'ignore-client-bandwidth': True, 'alpn': ['h3']})
        config['listeners'].append(listener)
    config['proxies'] = [{'name': 'egress-' + p, 'type': 'socks5', 'server': ROLES[p]['address'],
                         'port': 1080, 'username': p, 'password': password, 'udp': False}
                        for p, password in secret['backends'].items()]
    config['rules'] = blocked_rules(site)
    for device in site['devices']:
        user = device['id']
        udp = 'REJECT' if device['udp_policy'] == 'deny' else 'DIRECT'
        config['rules'].append(f'AND,((IN-USER,{user}),(NETWORK,UDP)),{udp}')
        target = 'DIRECT' if device['tcp_profile'] == 'native' else 'egress-' + device['tcp_profile']
        config['rules'].append(f'IN-USER,{user},{target}')
    # REALITY handshake is not an authenticated device flow; its only fallback
    # is an exact public decoy after the identity routes, never before them.
    if site['protocols']['vless']['enabled']:
        config['rules'].append(f'AND,((DOMAIN,{site["reality"]["server_name"]}),(DST-PORT,{site["reality"]["target_port"]})),DIRECT')
    config['rules'].append('MATCH,REJECT')
    return config

def backend(site, secret, profile):
    config = base()
    config['listeners'] = [{'name': profile + '-socks', 'type': 'socks',
                            'listen': ROLES[profile]['address'], 'port': 1080,
                            'users': [{'username': profile, 'password': secret['backends'][profile]}]}]
    config['dns'] = {'enable': True, 'listen': '127.0.0.1:1053', 'ipv6': False,
                     'enhanced-mode': 'redir-host', 'use-hosts': False, 'use-system-hosts': False,
                     'nameserver': ['udp://' + site['host']['dns'] + ':53'],
                     'default-nameserver': [site['host']['dns']]}
    config['rules'] = blocked_rules(site) + ['NETWORK,UDP,REJECT', 'MATCH,DIRECT']
    return config

def client(site, secret, device):
    config = base(); nodes = []
    for protocol in device['protocols']:
        node = {'name': device['id'] + '-' + protocol, 'type': protocol,
                'server': site['host']['server_name'], 'port': site['protocols'][protocol]['port']}
        if protocol == 'vless':
            node.update({'uuid': secret['devices'][device['id']][protocol], 'network': 'tcp',
                         'tls': True, 'flow': 'xtls-rprx-vision', 'servername': site['reality']['server_name'],
                         'client-fingerprint': 'chrome', 'udp': device['udp_policy'] != 'deny',
                         'reality-opts': {'public-key': secret['reality']['public_key'], 'short-id': secret['reality']['short_id']}})
        else:
            node.update({'password': secret['devices'][device['id']][protocol],
                         'sni': site['subscription']['hostname'], 'skip-cert-verify': False})
            if protocol == 'anytls':
                node.update({'udp': device['udp_policy'] != 'deny', 'client-fingerprint': 'chrome'})
        nodes.append(node)
    config.update({'mixed-port': 7890, 'proxies': nodes,
                   'proxy-groups': [{'name': 'VPS', 'type': 'select', 'proxies': [x['name'] for x in nodes]}]})
    rules = []
    if device['ssh_direct']:
        rules.append(f'AND,((IP-CIDR,{site["host"]["public_ipv4"]}/32),(NETWORK,TCP),(DST-PORT,{site["host"]["ssh_port"]})),DIRECT')
    if site['subscription']['enabled']:
        rules.append(f'AND,((DOMAIN,{site["subscription"]["hostname"]}),(NETWORK,TCP),(DST-PORT,{site["subscription"]["port"]})),DIRECT')
    if device['udp_policy'] == 'deny':
        rules.append('NETWORK,UDP,REJECT')
    config['rules'] = rules + ['MATCH,VPS']
    return config

def blocked_set(site):
    nets = [ipaddress.IPv4Network(x) for x in (*BLOCKED, site['host']['public_ipv4'] + '/32')]
    return 'set blocked_v4 { type ipv4_addr; flags interval; elements = { ' + ', '.join(map(str, ipaddress.collapse_addresses(nets))) + ' }; }'

def guard(site, profiles):
    replies = []
    for protocol, item in site['protocols'].items():
        if item['enabled']:
            proto = 'udp' if protocol == 'hysteria2' else 'tcp'
            replies.append(f'ct direction reply ct state established {proto} sport {item["port"]} return')
    exceptions = [f'oifname "{ROLES[p]["host_if"]}" ip daddr {ROLES[p]["address"]} tcp dport 1080 return' for p in profiles]
    return '\n'.join(['table inet vps_guard {', blocked_set(site), 'chain guard {',
        'meta nfproto ipv6 counter drop', *replies, *exceptions,
        f'ip daddr {site["host"]["dns"]} meta l4proto {{ tcp, udp }} th dport 53 return',
        'ip daddr @blocked_v4 counter drop', 'fib daddr type { local, broadcast, multicast } counter drop',
        'oifname "lo" counter drop', 'meta nfproto ipv4 meta l4proto { tcp, udp } return', 'counter drop', '}',
        'chain output { type filter hook output priority 10; policy accept; meta skuid @MIHOMO_UID@ jump guard; }', '}']) + '\n'

def namespace_guard(site, profile):
    r = ROLES[profile]
    return f'''table inet vps_backend {{
 {blocked_set(site)}
 chain input {{ type filter hook input priority 10; policy drop;
  meta nfproto ipv6 drop
  ct direction reply ct state established,related accept
  iifname "e0" ip saddr {r['host_ip']} tcp dport 1080 accept
 }}
 chain output {{ type filter hook output priority 10; policy drop;
  meta nfproto ipv6 drop
  ct direction reply ct state established tcp sport 1080 accept
  ip daddr {site['host']['dns']} meta l4proto {{ tcp, udp }} th dport 53 accept
  ip daddr @blocked_v4 counter drop
  fib daddr type {{ local, broadcast, multicast }} drop
  oifname "lo" drop
  meta nfproto ipv4 meta l4proto tcp accept
 }}
}}
'''

def caddy(site, secret):
    lines = ['{', ' admin 127.0.0.1:2019', ' auto_https off', '}',
             f'https://{site["subscription"]["hostname"]}:{site["subscription"]["port"]} {{',
             ' tls /etc/vps-network/tls/fullchain.pem /etc/vps-network/tls/privkey.pem',
             ' header Cache-Control "no-store"', ' header Referrer-Policy "no-referrer"',
             ' handle /health {', '  respond "ok" 200', ' }']
    for device in site['devices']:
        token = secret['devices'][device['id']]['subscription_token']
        lines += [f' handle /{token}.yaml {{', '  root * /srv/vps-network/subscriptions',
                  f'  rewrite * /{device["id"]}.json', '  file_server', ' }']
    return '\n'.join(lines + [' respond 404', '}']) + '\n'

def units(site, profiles):
    services = {}
    backend_names = ['vps-tcpfp-' + p + '.service' for p in profiles]
    depends = ' '.join(['vps-guard.service'] + backend_names)
    services['vps-mihomo.service'] = f'''[Unit]
Description=Private VPS network frontend
Wants=network-online.target
After=network-online.target {depends}
BindsTo={depends}
[Service]
User=vps-mihomo
Group=vps-controller
SupplementaryGroups=vps-tls
RuntimeDirectory=vps-mihomo
RuntimeDirectoryMode=0750
UMask=0007
LoadCredential=config.json:{ETC}/mihomo.json
ExecStartPre={ROOT}/mihomo -t -d /var/lib/vps-mihomo -f %d/config.json
ExecStart={ROOT}/mihomo -d /var/lib/vps-mihomo -f %d/config.json
Restart=on-failure
RestartSec=3
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/lib/vps-mihomo
CapabilityBoundingSet=
RestrictAddressFamilies=AF_INET AF_UNIX
[Install]
WantedBy=multi-user.target
'''
    services['vps-guard.service'] = f'''[Unit]
Description=Frontend UID egress guard
Before=vps-mihomo.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/python3 {ROOT}/guard.py start --apply
ExecStop=/usr/bin/python3 {ROOT}/guard.py stop --apply
RuntimeDirectory=vps-guard
RuntimeDirectoryMode=0700
RuntimeDirectoryPreserve=yes
[Install]
WantedBy=multi-user.target
'''
    if profiles:
        services['vps-network.service'] = f'''[Unit]
Description=Owned TCP fingerprint namespaces
Wants=network-online.target
After=network-online.target
Before={' '.join(backend_names)}
[Service]
Type=oneshot
RemainAfterExit=yes
RuntimeDirectory=vps-network
RuntimeDirectoryMode=0700
RuntimeDirectoryPreserve=yes
ExecStart=/usr/bin/python3 {ROOT}/network.py start --apply
ExecStop=/usr/bin/python3 {ROOT}/network.py stop --apply
TimeoutStartSec=90
[Install]
WantedBy=multi-user.target
'''
    for profile in profiles:
        services['vps-tcpfp-' + profile + '.service'] = f'''[Unit]
Description=TCP fingerprint {profile} backend
After=vps-network.service
BindsTo=vps-network.service
Before=vps-mihomo.service
[Service]
DynamicUser=yes
RuntimeDirectory=vps-tcpfp-{profile}
NetworkNamespacePath=/run/netns/{ROLES[profile]['namespace']}
LoadCredential=config.json:{ETC}/{profile}.json
ExecStart={ROOT}/mihomo -d /run/vps-tcpfp-{profile} -f %d/config.json
Restart=on-failure
RestartSec=2
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
CapabilityBoundingSet=
RestrictAddressFamilies=AF_INET AF_UNIX
[Install]
WantedBy=multi-user.target
'''
    return services

def forward_rules(site, profiles):
    roles = [ROLES[p] for p in profiles]
    interfaces = '{ ' + ', '.join('"' + r['host_if'] + '"' for r in roles) + ' }'
    addresses = '{ ' + ', '.join(r['address'] for r in roles) + ' }'
    spoof = '\n'.join(f'iifname "{r["host_if"]}" ip saddr != {r["address"]} drop' for r in roles)
    return f'''table inet vps_network {{
 {blocked_set(site)}
 chain input {{ type filter hook input priority -5; policy accept;
  iifname {interfaces} ct direction reply ct state established,related accept
  iifname {interfaces} counter drop
 }}
 chain forward {{ type filter hook forward priority -5; policy accept;
  iifname {interfaces} meta nfproto ipv6 drop
  {spoof}
  iifname {interfaces} ip daddr @blocked_v4 counter drop
  iifname {interfaces} oifname != "{site['host']['wan']}" drop
  iifname {interfaces} meta l4proto tcp accept
  iifname {interfaces} ip daddr {site['host']['dns']} udp dport 53 accept
  iifname {interfaces} drop
  oifname {interfaces} iifname "{site['host']['wan']}" ct direction reply ct state established,related accept
  oifname {interfaces} drop
 }}
}}
table ip vps_nat {{
 chain postrouting {{ type nat hook postrouting priority srcnat; policy accept;
  oifname "{site['host']['wan']}" ip saddr {addresses} masquerade
 }}
}}
'''
