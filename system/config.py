"""Strict, non-secret site schema and separately supplied credentials."""
from __future__ import annotations
import base64
import ipaddress
import re
import uuid
import subprocess

BLOCKED = ('0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
           '169.254.0.0/16', '172.16.0.0/12', '192.0.0.0/24', '192.0.2.0/24',
           '192.88.99.0/24', '192.168.0.0/16', '198.18.0.0/15',
           '198.51.100.0/24', '203.0.113.0/24', '224.0.0.0/4', '240.0.0.0/4')
ROLES = {
    'windows': {'namespace': 'vps-windows', 'host_if': 'vpn-win0', 'host_ip': '10.203.1.1',
                'address': '10.203.1.2', 'network': '10.203.1.0/30', 'section': 'tc_win'},
    'ios': {'namespace': 'vps-ios', 'host_if': 'vpn-ios0', 'host_ip': '10.203.2.1',
            'address': '10.203.2.2', 'network': '10.203.2.0/30', 'section': 'tc_ios'},
}
PROTOCOLS = ('vless', 'hysteria2', 'anytls')

def require(condition, message):
    if not condition:
        raise ValueError(message)

def keys(obj, expected, label):
    require(isinstance(obj, dict), label + ' must be an object')
    require(set(obj) == set(expected), label + ' has missing or unknown fields')

def name(value, label):
    require(isinstance(value, str) and re.fullmatch(r'[a-z][a-z0-9-]{0,31}', value), label + ' is invalid')

def hostname(value):
    require(isinstance(value, str) and len(value) <= 253 and re.fullmatch(
        r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', value), 'Invalid hostname')
    require(all(x and len(x) <= 63 and not x.startswith('-') and not x.endswith('-')
                for x in value.split('.')), 'Invalid hostname labels')

def port(value):
    require(type(value) is int and 1024 <= value <= 65535, 'Ports must be integers between 1024 and 65535')

def boolean(value):
    require(type(value) is bool, 'Expected boolean, not string or integer')

def validate_site(site):
    keys(site, ('schema', 'host', 'reality', 'protocols', 'devices', 'tcpfp',
                'subscription', 'bbr', 'usage'), 'site')
    require(site['schema'] == 1, 'Unsupported schema')
    host = site['host']
    keys(host, ('public_ipv4', 'server_name', 'wan', 'ssh_port', 'dns'), 'host')
    ipaddress.IPv4Address(host['public_ipv4'])
    hostname(host['server_name'])
    require(isinstance(host['wan'], str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', host['wan']), 'Invalid WAN')
    require(host['wan'] not in ('lo', 'vpn-win0', 'vpn-ios0'), 'Invalid WAN role')
    port(host['ssh_port'])
    resolver = ipaddress.IPv4Address(host['dns'])
    require(not any(resolver in ipaddress.ip_network(x) for x in BLOCKED), 'DNS must be a public IPv4 resolver')
    require(str(resolver) != host['public_ipv4'], 'DNS cannot be this host')
    keys(site['reality'], ('server_name', 'target_port'), 'reality')
    hostname(site['reality']['server_name'])
    require(type(site['reality']['target_port']) is int and 1 <= site['reality']['target_port'] <= 65535, 'Invalid REALITY target port')
    keys(site['protocols'], PROTOCOLS, 'protocols')
    endpoints = {('tcp', host['ssh_port'])}
    for protocol, item in site['protocols'].items():
        keys(item, ('enabled', 'port'), protocol)
        boolean(item['enabled']); port(item['port'])
        if item['enabled']:
            endpoint = ('udp' if protocol == 'hysteria2' else 'tcp', item['port'])
            require(endpoint not in endpoints, 'Conflicting listening ports')
            endpoints.add(endpoint)
    require(any(p['enabled'] for p in site['protocols'].values()), 'At least one protocol is required')
    keys(site['tcpfp'], ('enabled', 'mtu'), 'tcpfp')
    boolean(site['tcpfp']['enabled'])
    require(type(site['tcpfp']['mtu']) is int and 1280 <= site['tcpfp']['mtu'] <= 1500, 'Invalid MTU')
    keys(site['subscription'], ('enabled', 'hostname', 'port'), 'subscription')
    boolean(site['subscription']['enabled']); hostname(site['subscription']['hostname']); port(site['subscription']['port'])
    if site['subscription']['enabled']:
        require(('tcp', site['subscription']['port']) not in endpoints, 'Subscription port conflict')
    keys(site['bbr'], ('host', 'namespaces'), 'bbr')
    boolean(site['bbr']['host']); boolean(site['bbr']['namespaces'])
    require(not site['bbr']['namespaces'] or site['tcpfp']['enabled'], 'Namespace BBR needs TCPFP')
    keys(site['usage'], ('enabled', 'interval_seconds'), 'usage')
    boolean(site['usage']['enabled'])
    require(type(site['usage']['interval_seconds']) is int and 1 <= site['usage']['interval_seconds'] <= 300, 'Invalid usage interval')
    require(isinstance(site['devices'], list) and 0 < len(site['devices']) <= 32, 'Expected 1..32 private devices')
    ids = set()
    for device in site['devices']:
        keys(device, ('id', 'tcp_profile', 'udp_policy', 'protocols', 'ssh_direct'), 'device')
        name(device['id'], 'Device ID'); require(device['id'] not in ids, 'Duplicate device ID'); ids.add(device['id'])
        require(device['tcp_profile'] in ('native', *ROLES), 'Unknown TCP profile')
        require(device['tcp_profile'] == 'native' or site['tcpfp']['enabled'], 'TCP profile requires TCPFP')
        require(device['udp_policy'] in ('deny', 'direct'), 'UDP policy must be deny or explicit direct')
        boolean(device['ssh_direct'])
        require(isinstance(device['protocols'], list) and device['protocols'] and
                len(set(device['protocols'])) == len(device['protocols']), 'Invalid device protocols')
        require(all(p in PROTOCOLS and site['protocols'][p]['enabled'] for p in device['protocols']), 'Device references disabled protocol')
    for protocol, options in site['protocols'].items():
        require(not options['enabled'] or any(protocol in d['protocols'] for d in site['devices']), 'Enabled protocol has no device credentials')
    return site

def validate_secrets(site, secrets):
    keys(secrets, ('reality', 'devices', 'backends'), 'secrets')
    keys(secrets['reality'], ('private_key', 'public_key', 'short_id'), 'REALITY secrets')
    for field in ('private_key', 'public_key'):
        value = secrets['reality'][field]
        require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', value), 'Invalid X25519 key encoding')
        require(len(base64.urlsafe_b64decode(value + '=')) == 32, 'Invalid X25519 key length')
    require(secrets['reality']['private_key'] != secrets['reality']['public_key'], 'REALITY keys must differ')
    private_raw = base64.urlsafe_b64decode(secrets['reality']['private_key'] + '=')
    der = bytes.fromhex('302e020100300506032b656e04220420') + private_raw
    derived = subprocess.run(['openssl', 'pkey', '-inform', 'DER', '-pubout', '-outform', 'DER'],
        input=der, capture_output=True, check=True).stdout
    require(derived[:12] == bytes.fromhex('302a300506032b656e032100'), 'Invalid X25519 public key format')
    require(base64.urlsafe_b64encode(derived[12:]).decode().rstrip('=') == secrets['reality']['public_key'], 'REALITY key pair mismatch')
    require(isinstance(secrets['reality']['short_id'], str) and re.fullmatch(r'[a-f0-9]{16}', secrets['reality']['short_id']), 'Invalid short ID')
    require(set(secrets['devices']) == {d['id'] for d in site['devices']}, 'Device credentials mismatch')
    seen = set()
    for device in site['devices']:
        value = secrets['devices'][device['id']]
        fields = {'subscription_token'} | set(device['protocols'])
        keys(value, fields, 'Device secrets')
        for field, credential in value.items():
            require(isinstance(credential, str), 'Credential must be a string')
            if field == 'vless':
                require(str(uuid.UUID(credential)) == credential and uuid.UUID(credential).version == 4, 'Expected canonical UUID4')
            else:
                require(re.fullmatch(r'[A-Za-z0-9_-]{32,128}', credential), 'Credentials need 32..128 URL-safe characters')
            require(credential not in seen, 'Credentials cannot be reused'); seen.add(credential)
    profiles = {d['tcp_profile'] for d in site['devices']} - {'native'}
    require(set(secrets['backends']) == profiles, 'Backend credentials mismatch')
    for credential in secrets['backends'].values():
        require(isinstance(credential, str) and re.fullmatch(r'[A-Za-z0-9_-]{32,128}', credential), 'Invalid backend password')
        require(credential not in seen, 'Credentials cannot be reused'); seen.add(credential)
    return secrets
