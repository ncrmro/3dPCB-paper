"""End-to-end CLI smoke: parses, emits YAML, exit codes are right."""

from __future__ import annotations

import io
import os
from contextlib import redirect_stdout, redirect_stderr

import yaml

from optimizer.cli import main


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TIER1_PLAN = os.path.join(REPO_ROOT, "printable_pcb", "spike_v2", "substrate_plan.md")
TIER2_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "spike_v2_tier2_with_oled.md")


def test_cli_happy_path_emits_yaml(tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main([TIER1_PLAN])
    assert rc == 0
    doc = yaml.safe_load(buf.getvalue())
    assert "proposals" in doc
    assert "declined" in doc
    assert "metrics" in doc
    assert doc["metrics"]["topology"] == "per_signal"


def test_cli_bundled_topology_emits_alt_block():
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main([TIER1_PLAN, "--topology", "bundled"])
    assert rc == 0
    doc = yaml.safe_load(buf.getvalue())
    assert "metrics_alternative" in doc
    bus_block = doc["metrics_alternative"]["buses"]["primary_i2c"]
    assert bus_block["visit_order"][0] == "ESP32"
    assert bus_block["total_vias"] == 0


def test_cli_missing_file_returns_nonzero():
    err = io.StringIO()
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(["/tmp/does/not/exist.md"])
    assert rc != 0


def test_cli_json_format():
    import json
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main([TIER1_PLAN, "--format", "json"])
    assert rc == 0
    doc = json.loads(buf.getvalue())
    assert "metrics" in doc
