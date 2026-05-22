"""Static net-sharing optimizer.

Deterministic replacement for the LLM-driven `optimize_net_sharing`
step in `.deepwork/jobs/printable_pcb/job.yml`. Parses a substrate
plan, applies class-based eligibility + proximity rules, and emits
proposals YAML. See issue #42 and the package's docstrings for the
schema and data flow.
"""
