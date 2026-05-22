"""Command-line entrypoint for the static net-sharing optimizer.

Usage:
    optimize-nets <substrate_plan.md> [--weights weights.yaml]
                                     [--topology per_signal|bundled]
                                     [--format yaml|json]
"""

from __future__ import annotations

import argparse
import json
import sys

import yaml

from .plan_parser import parse_plan
from .proposals import build_proposals
from .weights import load_weights


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="optimize-nets",
        description="Static net-sharing optimizer for 3D-printed PCB substrates.",
    )
    p.add_argument("plan_path", help="Path to substrate_plan.md")
    p.add_argument("--weights", default=None, help="Path to weights YAML (defaults shipped)")
    p.add_argument(
        "--topology",
        choices=["per_signal", "bundled"],
        default=None,
        help="Override every bus's topology setting.",
    )
    p.add_argument(
        "--format",
        choices=["yaml", "json"],
        default="yaml",
        help="Output format (default: yaml).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    try:
        plan = parse_plan(args.plan_path)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"error parsing plan: {e}", file=sys.stderr)
        return 3

    try:
        weights = load_weights(args.weights)
    except Exception as e:
        print(f"error loading weights: {e}", file=sys.stderr)
        return 4

    doc = build_proposals(plan, weights, topology_override=args.topology)
    if args.format == "json":
        body = {
            "proposals": doc.proposals,
            "declined": doc.declined,
            "metrics": doc.metrics,
        }
        if doc.metrics_alternative is not None:
            body["metrics_alternative"] = doc.metrics_alternative
        if doc.warnings:
            body["warnings"] = doc.warnings
        print(json.dumps(body, indent=2))
    else:
        print(doc.to_yaml(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
