"""YAML → CircuitSpec loader.

`load_spec` reads a YAML file and runs it through Pydantic validation.
Errors surface as `pydantic.ValidationError` with the source field path
identified — same UX as any other Pydantic-validated config.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import yaml

from circuit.models import CircuitSpec


def load_spec(path: Union[str, Path]) -> CircuitSpec:
    """Read a YAML circuit spec and return a validated CircuitSpec.

    Raises:
        FileNotFoundError: the path doesn't exist.
        yaml.YAMLError: the file isn't valid YAML.
        pydantic.ValidationError: the document doesn't match the schema.
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(
            f"{p}: top-level YAML must be a mapping, got {type(data).__name__}"
        )
    return CircuitSpec.model_validate(data)
