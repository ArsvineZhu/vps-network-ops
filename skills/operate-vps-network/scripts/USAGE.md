# Tools and verification

These tools do not modify the VPS or publish subscription links. Keep generated files
private. JSON-formatted YAML is accepted by Mihomo; legacy Clash is not compatible
with these VLESS/REALITY fields. GUI import behavior still needs testing on the
installed client.

## Explicit TCP routing experiment (separate from unit tests)

See [experiments/tcp-device-routing](../experiments/tcp-device-routing/README.md).
That source executes on import, opens loopback listeners and runs official Mihomo;
it deliberately lives outside this scripts directory and its unittest discovery.
It proves per-user routing and TTL selection, not full Windows/iOS TCP spoofing.
Copy it to a private disposable directory and follow its README before reproducing.

## One node

Create private-node.json locally with server, port (integer), uuid, servername,
public_key, short_id; optional name/fingerprint. Never include the server private key.

    python3 scripts/clash_profile.py private-node.json profile.yaml
    python3 scripts/clash_profile.py private-node.json provider.yaml --kind provider

profile.yaml is a complete local profile (mixed port 7897). provider.yaml contains
only proxies and must be referenced by a complete profile. Neither is an HTTP
subscription URL. These are base profiles, not a lossless export of the live
subscription: they do not merge per-person SSH/DIRECT exceptions or custom DNS
settings. Check a sanitized diff before replacing any maintained profile. The fixed protocol is VLESS TCP REALITY with xtls-rprx-vision.

Optional categories:

    python3 scripts/clash_profile.py private-node.json categories.yaml --rules categorized

All categories (including China and private destinations) initially use VPS-Select.
Selecting DIRECT is an explicit user decision that exposes that traffic to the local
network. Private destinations via the protected VPS will normally fail, intentionally.
The optional profile downloads official MetaCubeX rule sets when run. It is not an
offline profile. No pointless automatic/fallback group is generated for a single VPS.
Browser WebRTC/direct UDP is not controlled by a SOCKS profile alone.

## Separate person

Create a public-template.json with server, port, servername, public_key, short_id,
optional fingerprint. Do NOT put an existing user's UUID into this template.

    python3 scripts/new_member.py public-template.json colleague1 ./colleague1
    python3 scripts/new_member.py public-template.json colleague2 ./colleague2 --rules categorized

Each new directory includes a `.gitignore` containing `*`, created before credential
files. This protects untracked bundle files from ordinary Git adds, but does not
untrack already tracked files or prevent force-adds. Keep bundles outside repositories
and never commit credentials.

Each new directory has a unique UUID, profile.yaml, provider.yaml, record.json and
server-user.pending.json. The latter is a candidate entry (username, uuid, flow; username is the real server field) for the chosen Mihomo
VLESS listener's users list, NOT a complete server config and NOT applied by this tool.
Before sharing: back up the server config; add only this user entry to the correct
listener; validate with the installed core; restart; wait for the actual listener;
test this specific credential. Preserve other users.
To revoke: remove that UUID on the server, validate/reload and test denial. Deleting
files or removing a subscription URL does not revoke access. Active sessions can
persist until closed/restarted. Server changes and distribution need authorization.

Windows: create and use these files in a private current-user-only directory. Python
0600/0700 modes do not enforce NTFS ACLs. Do not place bundles in a public Git repo.

## Windows isolated probe

PowerShell 5.1-compatible source was written but has NOT been executed on Windows
in the build environment. It therefore remains experimental until verified.

    .\scripts\mihomo_probe.ps1 -CorePath 'C:\path\mihomo.exe' -ProfilePath 'C:\private\profile.yaml' -ValidateOnly
    .\scripts\mihomo_probe.ps1 -CorePath 'C:\path\mihomo.exe' -ProfilePath 'C:\private\profile.yaml' -Url 'https://example.com/'

Input must be JSON-formatted YAML produced by this kit, one VLESS node only.
- Uses the specified installed trusted executable; no download.
- Builds a clean minimal config, not a copy of the user's runtime configuration.
- Creates current-user-only ACL directory before writing credentials.
- Reserves the same loopback port for TCP and UDP. A bind race after release remains
  possible; PID ownership/readiness checks fail safely rather than contacting another process.
- Disables TUN and internal DNS; doesn't change the system proxy, existing clients or routes.
- SOCKS5h keeps target DNS with the proxy path. Endpoint DNS can still use OS DNS.
- Existing Tailscale/OS routing still applies. Success while Tailscale is active does
  not demonstrate the VPS is reachable through the user's direct ISP path.
- Removes only its temporary directory and stops only its Process object.
- Suppresses raw core logs and secret-containing exception text.
- 200 proves that requested HTTPS transfer succeeded; it is not a full leak/UDP/NAT test.

## Linux read-only

    sudo bash scripts/vps_snapshot.sh
    sudo python3 scripts/wait_listener.py mihomo.service 8443 --seconds 10
    python3 scripts/test_tools.py

Review snapshot IPs/hostnames before sharing. No apt refresh or remote probes occur.
Core validation should use a private isolated data directory:

    mihomo -t -d /path/to/private-test-dir -f /path/to/profile.yaml

Tests performed: profile/member Python unit tests (8), Python syntax compilation, Bash syntax,
synthetic category defaults and two independent member UUID generation.
Parent verification: a synthetic generated standalone client profile and a synthetic server listener schema passed Mihomo 1.19.33 -t on the user computer. This only verifies parsing of those samples; placeholder templates are not runnable credentials. Not verified for this package: real server deployment, nft/systemd behavior, remote rule downloads, real multi-user revocation or leak tests. Treat the new Windows probe implementation as experimental until its own runtime verification is recorded.

## Approximate observed per-person usage

    python3 scripts/observed_usage.py --db /private/usage.sqlite --instance vps1 --inbound vless-in --users-file /private/users.json --snapshot /private/connections.json
    python3 scripts/observed_usage.py --db /private/usage.sqlite --instance vps1 --inbound vless-in --users-file /private/users.json --unix-socket /private/mihomo.sock
    python3 scripts/test_usage.py

The collector runs on POSIX only and rejects existing group/world-accessible databases or non-private parent directories. Windows ACLs are not emulated.
Linux Unix-domain socket is the only live API transport supported. No public TCP
controller is created or needed. Enable a socket only through a separately reviewed
server change with restrictive filesystem permissions. Optional --token-file reads
an already provisioned token; do not supply tokens in shell arguments. For reviewed
Mihomo v1.19.33 Unix sockets the server bypasses secret authentication, so this
option is NOT an access-control boundary. Protect the parent directory instead.
Use stable non-sensitive listener user names, e.g. friend1. Script records the exact
metadata.inboundUser supplied by the API, so do NOT use UUIDs/emails as user names.
Create the database directory with mode 0700 on POSIX; this collector does not run on Windows.
Snapshot input itself contains destinations and must not be shared or committed.

Each invocation imports current connection counters, transactionally stores last
seen connection ID/counters and adds positive increments to per-user totals. Repeated
identical observations do not double-count. Disappeared connections and counter
resets are logged. Poll errors log a gap/error row. Empty successful results mean
zero observed active connections, not that every user's device is offline.
polls timestamps expose scheduling gaps; the tool does not detect a restart reliably
without a server boot identifier. New connection IDs begin a new watermark; a
counter decrease is recorded as reset. Persist the DB across collector restarts.

This is NOT billing: short connections entirely between polls and final bytes after
the last observation are missed. Connections present at first observation contribute
their lifetime count, so totals are NOT exact bytes since collection startup.
Per-user "active" means observed in /connections, not device online/offline.
Rows without inboundUser are skipped. No IP/domain/UUID protocol fields are stored,
but connection IDs and operator-defined user labels are stored locally.
A schedule is not installed automatically; choose a modest interval such as 10–30s
only after controller/snapshot access has been verified. More frequent polling still
cannot make this exact. Tests cover repeated polls, increments, disappearance,
new connections, reset and atomic invalid-input rejection (7 usage tests passed).

Only records with exact metadata.inboundName equal to --inbound AND inboundUser in
--users-file (JSON array, e.g. ["friend1","friend2"]) enter totals. Others are counted
as ignored, not attributed. Missing inboundName is ignored rather than guessed.
API-provided names are not an independently authenticated identity; duplicate user
names within the same listener merge totals. Use one unique label and UUID per person.


Accounting fixes: watermarks are retained indefinitely, including disappeared connection
IDs, and each direction uses max(previous,current). Lower or replayed samples contribute
zero until exceeding that direction's previous high-water mark. This intentionally
undercounts if a server improperly reuses IDs after a reset. Do not delete watermarks
to save space without acknowledging loss of replay protection. DB size grows with
observed connection IDs. Each DB binds to one --instance and --inbound in the same
transaction as accounting; different scopes and unbound legacy DBs are rejected.
Changes in whitelist do not erase historical totals. Snapshot imports have no trusted
source timestamp, so "active" reflects the latest imported sample, not real-time online
status. Unknown never-before-seen stale IDs can still contribute old lifetime counts.

The optional Private category is DOMAIN classification only, NOT private-IP coverage
and NOT a firewall. Server destination isolation still relies on reviewed guard rules.
YouTube is before Google's broader domain set. Rule groups are reserved Route-* names.

## Local leaf certificate check (read-only)

    python3 scripts/certificate_check.py --cert /private/leaf.pem --hostname sub.example.com --min-days 7
    python3 scripts/test_certificate_check.py

Requires trusted installed OpenSSL. Checks the first PEM certificate's hostname,
not-before and not-after dates, using the local UTC clock. No private key access,
DNS request, credential storage, certificate issuance, server changes or renewal
schedule. Fullchain trust, key matching and the certificate actually served by the
endpoint are deliberately outside its scope. A self-signed certificate can PASS:
that does not make it trusted. Do not treat this helper as deployment acceptance.
Pass a locally trusted file path, not an untrusted device/FIFO. Output is a status,
without certificate, private key, account identifiers or raw command errors.
Five local tests cover accepted hostname, rejected mismatch, short remaining validity,
missing file and rejected option-like hostname. They use disposable synthetic
self-signed certificates and do not contact a CA or VPS.

## Persistent usage sampler: templates and production scope

`usage_daemon.py` and `check_socket_dir.py` have offline tests; service, drop-in and
collector config templates are in references/templates. They are not deployed by
copying this repository. The reviewed target paths and actual account must match;
the current daemon deliberately rejects alternative socket/database paths.

    python3 scripts/test_daemon.py

Official v1.19.33 Unix controller uses a 0666 socket and bypasses secret auth.
A private 0700 parent directory and pre-start ownership checks are mandatory;
API administrative access requires explicit permission. No socket is opened here.
`observed_usage.py` now accepts idle connections:null and records initial errors.
The sampler defaults to 5-second polls (config range 1–10), persists lifecycle/gap
states, and stops at a 512MiB database cap without deleting watermarks. This is
still approximate observation, not accounting. The later production report confirms real Unix-socket privilege denial and a
successful first sample with the service active. Per-person production attribution,
long-running stability and restart persistence remain unverified. See deployment-record.
