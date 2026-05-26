"""Discover every spec under `code/cad/specs/` and register it.

For each `<stem>.yaml` we synthesise an AnchorSCAD `Shape` subclass
named `Board_<stem>` so the existing `registry.auto_register_module`
picks it up alongside the vitamin shapes. Each subclass renders the
substrate built from its YAML.

Discovery runs at import time — importing `board` is enough to populate
both `DEVICE_REGISTRY` (via `board.device_library`) and the per-spec
Shape registry (via this module).
"""

from __future__ import annotations

import os
from pathlib import Path

import anchorscad as ad
from anchorscad import datatree

from board.build import BoardSubstrate, _BOARD_REGISTRY
from board.loader import load_board


def _specs_dir() -> Path:
    # board/spec_discovery.py is at code/cad/src/board/spec_discovery.py;
    # specs at code/cad/specs/. Walk up 3 levels.
    return Path(__file__).resolve().parent.parent.parent / "specs"


def _make_board_subclass(spec_name: str) -> type:
    """Build a fresh `@ad.shape @datatree` subclass with `spec_name`
    baked in as the default. AnchorSCAD's registry instantiates with
    no args and keys on the class name."""

    # Closure-captured spec_name fed through a function default so the
    # class body sees it as a local literal.
    def _make(default_name: str = spec_name):
        @ad.shape
        @datatree
        class _BoardForSpec(BoardSubstrate):
            name: str = default_name

        return _BoardForSpec

    cls = _make()
    # `Substrate_<name>` (not `Board_<name>`) so the GLB stem auto-
    # registry produces matches the gallery's existing `substrate_<name>`
    # manifest convention. The Board is the *spec*; the Substrate is
    # the *rendered output*.
    cls.__name__ = f"Substrate_{spec_name}"
    cls.__qualname__ = cls.__name__
    cls.__module__ = __name__
    return cls


SPEC_BOARDS: dict[str, type] = {}


def _discover() -> None:
    sd = _specs_dir()
    if not sd.is_dir():
        return
    for f in sorted(sd.iterdir()):
        if f.suffix != ".yaml":
            continue
        try:
            board_obj = load_board(f)
        except Exception as exc:  # noqa: BLE001 — keep discovery best-effort
            print(f"[board.spec_discovery] skip {f.name}: {exc}")
            continue
        _BOARD_REGISTRY[board_obj.name] = board_obj
        cls = _make_board_subclass(board_obj.name)
        SPEC_BOARDS[board_obj.name] = cls
        globals()[cls.__name__] = cls


_discover()
