#!/usr/bin/env bash
# Advisory chamfer-suggestion pass for the printable_pcb check_routing
# step.
#
# Usage: run_voxel_suggestions.sh
#
# Wraps `code/cad/bin/suggest-routes`, which emits a markdown table
# per substrate class listing axis-aligned L-bends whose 45° diagonal
# alternative would still satisfy the printable wall buffer. The
# script ALWAYS exits 0 — suggestions are advisory, not failures.
#
# The check_routing step should copy this output into a "Routing
# suggestions (advisory)" section of routing_check.md when a
# substrate has been materialized in substrate.py.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$REPO_ROOT"

exec nix develop ./code/cad -c bash -c "code/cad/bin/suggest-routes $*"
