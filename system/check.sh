#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1
python3 -m unittest discover -s system/tests -p 'test_*.py' -v
python3 -m unittest discover -s system/ansible -p 'test_*.py' -v
python3 -m unittest discover -s skills/operate-vps-network/scripts -p 'test_*.py' -v
bash -n skills/operate-vps-network/scripts/vps_snapshot.sh
bash system/tcpfp/tests/run.sh
python3 - <<'PY'
import ast
from pathlib import Path
for root in ('system', 'skills/operate-vps-network/scripts'):
    for p in Path(root).rglob('*.py'):
        ast.parse(p.read_text(), filename=str(p))
print('Python source syntax passed')
PY
git diff --check
