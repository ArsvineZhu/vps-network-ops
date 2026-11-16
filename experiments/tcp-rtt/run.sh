#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "Usage: run.sh PROBE MIHOMO OUTPUT" >&2
    exit 2
fi
probe=$(realpath "$1")
mihomo=$(realpath "$2")
output=$(realpath -m "$3")
lab="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lab.py"
mkdir -p "$output"
failed=0

for policy in handshake data; do
    for delay in 0 10 25 50 75 100; do
        python3 "$lab" run --probe "$probe" --mihomo "$mihomo" \
            --output "$output/screen-$policy-$delay" --count 10 \
            --ack-policy "$policy" --ack-delay "$delay" --timestamps 0 \
            --client-delay-ms 100 --rate-mbit 100 --queue-limit 10000 || failed=1
    done
done

for timestamps in 0 1; do
    sizes=(1024)
    if [[ $timestamps -eq 0 ]]; then
        sizes+=(65536 4194304)
    fi
    for size in "${sizes[@]}"; do
        for delay in 0 50 100; do
            python3 "$lab" run --probe "$probe" --mihomo "$mihomo" \
                --output "$output/measure-ts$timestamps-size$size-delay$delay" --count 30 \
                --ack-policy data --ack-delay "$delay" --timestamps "$timestamps" --size "$size" \
                --client-delay-ms 100 --rate-mbit 100 --queue-limit 10000 || failed=1
        done
    done
done

for delay in 0 50; do
    python3 "$lab" run --probe "$probe" --mihomo "$mihomo" \
        --output "$output/idle-handshake-$delay" --count 10 \
        --ack-policy handshake --ack-delay "$delay" --handshake-control --timestamps 0 || failed=1
done
for delay in 25 75; do
    python3 "$lab" run --probe "$probe" --mihomo "$mihomo" \
        --output "$output/all-delay-$delay" --count 30 --ack-policy none \
        --client-delay-ms 100 --server-delay-ms "$delay" \
        --rate-mbit 100 --queue-limit 10000 --timestamps 0 || failed=1
done
exit "$failed"
