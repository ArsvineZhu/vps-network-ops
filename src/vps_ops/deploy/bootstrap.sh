#!/bin/bash
set -euo pipefail
umask 077
cd /var/lib/vps-ops/deploy
python3 preflight.py
apt-get -o DPkg::Lock::Timeout=300 update
DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300 install -y --no-remove --no-install-recommends ansible-core python3-venv python3-yaml
(
    umask 022
    python3 -m venv --system-site-packages /opt/vps-ops
    /opt/vps-ops/bin/pip install ./*.whl
    /opt/vps-ops/bin/pip install --no-deps --force-reinstall ./*.whl
)
chmod -R a+rX /opt/vps-ops
ln -sf /opt/vps-ops/bin/vps-ops /usr/local/bin/vps-ops
python3 - <<'PYCONFIG'
import json,os
from pathlib import Path
p=Path("node.json")
c=json.loads(p.read_text())
c["ssh_port"]=int(os.environ["SSH_CONNECTION"].split()[3])
p.write_text(json.dumps(c))
Path("ansible-vars.json").write_text(json.dumps({"node":c}))
PYCONFIG
ansible-playbook -i localhost, -c local base.yaml -e @ansible-vars.json
echo VPS_OPS_KEY_READY
read -r confirmed
[[ $confirmed == KEY_VERIFIED ]] || exit 1
install -d -m 0700 /etc/vps-ops
cp node.json /etc/vps-ops/deployment.json
chmod 600 /etc/vps-ops/deployment.json
if [[ -e /var/run/reboot-required ]]; then
    systemctl reboot
    exit 42
fi
ansible-playbook -i localhost, -c local apply.yaml -e @ansible-vars.json
/opt/vps-ops/bin/python -m vps_ops.deploy.server finish /var/lib/vps-ops/deploy
flock -u 9
exec 9>&-
echo VPS_OPS_READY
exec /usr/local/bin/vps-ops shell
