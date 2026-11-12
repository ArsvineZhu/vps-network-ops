#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
make -B syn_rewrite.o "$@"
sha256sum syn_rewrite.c syn_rewrite.o
