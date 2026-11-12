#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
TMP=$(mktemp -d "${TMPDIR:-/tmp}/tcpfp-tests.XXXXXXXX")
trap 'rm -rf -- "$TMP"' EXIT INT TERM
CC=${CC:-gcc}
"$CC" -std=gnu11 -O2 -g -Wall -Wextra -Werror -fsanitize=address,undefined \
    -Itests tests/test_rewrite.c -o "$TMP/test_rewrite"
# The execution service uses ptrace; LeakSanitizer cannot run under ptrace.
# Tests allocate no heap memory. ASan/UBSan checks remain enabled.
ASAN_OPTIONS=detect_leaks=0 "$TMP/test_rewrite"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 ebpf/lab.py
