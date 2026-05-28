"""Off-the-shelf connector catalog.

A `Connector` describes a real, buyable header (e.g. a 1×4 female header
at 2.54 mm pitch): how big a plastic pedestal to print around the pin
body, and the standard height the device sits above the substrate when
this connector is used as a mount. Pin bores are drilled at the unified
`hole_bore_mm` (see build.py), not a per-connector value.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Connector(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    pin_count: int = Field(gt=0)
    pitch: float = Field(gt=0)              # mm between adjacent pin centres
    body_width: float = Field(gt=0)         # mm — pedestal extent along the pin row
    body_depth: float = Field(gt=0)         # mm — pedestal extent perpendicular to the pin row
    standard_height: float = Field(gt=0)    # mm — off-the-shelf height above the host PCB


# 2.54 mm female header strips — the workhorse mount for the OLED, and
# for any sensor breakout that needs to be elevated. body_depth picks up
# the typical 2.54 mm single-row plastic body width; body_width spans
# (pin_count - 1) * pitch + 2 * margin (margin = pitch/2 = 1.27 mm) so
# the plastic extends one half-pitch past the outer pins on each end.
def _strip_body_width(pin_count: int, pitch: float) -> float:
    return (pin_count - 1) * pitch + pitch


CONNECTOR_REGISTRY: dict[str, Connector] = {
    "female_1x4_2.54": Connector(
        name="female_1x4_2.54",
        pin_count=4,
        pitch=2.54,
        body_width=_strip_body_width(4, 2.54),
        body_depth=2.54,
        standard_height=8.5,
    ),
    "female_1x5_2.54": Connector(
        name="female_1x5_2.54",
        pin_count=5,
        pitch=2.54,
        body_width=_strip_body_width(5, 2.54),
        body_depth=2.54,
        standard_height=8.5,
    ),
    "female_1x6_2.54": Connector(
        name="female_1x6_2.54",
        pin_count=6,
        pitch=2.54,
        body_width=_strip_body_width(6, 2.54),
        body_depth=2.54,
        standard_height=8.5,
    ),
}


def get_connector(name: str) -> Connector:
    try:
        return CONNECTOR_REGISTRY[name]
    except KeyError as exc:
        known = ", ".join(sorted(CONNECTOR_REGISTRY))
        raise KeyError(
            f"unknown connector {name!r}; known: {known}"
        ) from exc
