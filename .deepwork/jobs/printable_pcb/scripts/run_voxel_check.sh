#!/usr/bin/env bash
# Voxel-test gate for the printable_pcb check_routing step.
#
# Usage: run_voxel_check.sh [SubstrateClassName]
#
# Runs the substrate routing voxel test. If a class name is given, the
# test is filtered to that parameterized case; otherwise all substrate
# classes are tested. Returns 0 on PASS, non-zero on FAIL.
#
# Output format on PASS:
#   PASS — all voxel checks green
# Output format on FAIL:
#   FAIL
#   <verbatim assertion lines from pytest, one per collision>

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$REPO_ROOT"

CLASS_FILTER="${1:-}"
PYTEST_ARGS=("code/cad/tests/test_substrate_routing.py" "-q" "--no-header")
if [[ -n "$CLASS_FILTER" ]]; then
    PYTEST_ARGS+=("-k" "$CLASS_FILTER")
fi

OUT=$(nix develop ./code/cad -c bash -c \
    "uv --project code/cad run pytest ${PYTEST_ARGS[*]}" 2>&1) || EXIT=$?
EXIT="${EXIT:-0}"

if [[ "$EXIT" -eq 0 ]]; then
    echo "PASS — all voxel checks green"
    exit 0
fi

echo "FAIL"
# Extract just the collision lines (E ...) — they name the signal pair
# and the (x, y) of the first conflicting voxel.
echo "$OUT" | grep -E "^E +(path|assert)" | sed 's/^E *//'
exit "$EXIT"
