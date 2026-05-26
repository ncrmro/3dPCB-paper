"""YAML → Board loader.

A spec file is a YAML document that validates against the `Board`
Pydantic model. Pydantic's `model_validate` does the heavy lifting; this
module is just file-IO + a small ergonomic shim that lets device
positions be written as `[x, y]` lists rather than `{x: , y: }` dicts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from board.board import Board


def load_board(path: str | Path) -> Board:
    """Read a YAML spec and return a validated `Board`."""
    p = Path(path)
    with p.open() as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(
            f"spec {p}: top-level must be a mapping, got {type(data).__name__}"
        )
    return Board.model_validate(data)


def dump_board(board: Board) -> str:
    """Round-trip the Board back to YAML. Used by the gallery's editor +
    `bin/substrate-report` so an edited spec can be persisted."""
    data: dict[str, Any] = board.model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=None)
