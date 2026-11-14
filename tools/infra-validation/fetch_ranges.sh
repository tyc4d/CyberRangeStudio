#!/usr/bin/env bash
# Resume a large download with parallel HTTP range requests and append the parts in order.
# Usage: fetch_ranges.sh <url> <output-file> <total-bytes> [parallel=10]
# The output file may already hold the first N bytes; only the remainder is fetched.
set -euo pipefail
url="$1"; out="$2"; total="$3"; n="${4:-10}"
have=0
[ -f "$out" ] && have=$(stat -c %s "$out")
if [ "$have" -ge "$total" ]; then echo "already complete: $have bytes"; exit 0; fi
chunk=$(( (total - have + n - 1) / n ))
dir="$(dirname "$out")"
pids=()
for i in $(seq 0 $((n - 1))); do
  start=$((have + i * chunk)); end=$((start + chunk - 1))
  [ "$start" -ge "$total" ] && break
  [ "$end" -ge "$total" ] && end=$((total - 1))
  curl -sS --fail --retry 8 --retry-delay 3 -r "$start-$end" -o "$dir/part.$(printf %02d "$i")" "$url" &
  pids+=($!)
done
for pid in "${pids[@]}"; do wait "$pid"; done
cat "$dir"/part.[0-9][0-9] >> "$out"
echo "assembled: $(stat -c %s "$out") bytes (expected $total)"
