"""Header mounts — elevated device carriers.

A device with a `Header` sits above the substrate on a printed pedestal
that holds a standard female header. The builder synthesises the pedestal
geometry from the connector's body footprint + height, and the router
sees the device's pins projected down to the substrate top (where they
physically solder).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from board.connectors import Connector, get_connector


class Header(BaseModel):
    """Standard female-header mount for a device.

    `height` defaults to the connector's `standard_height` — the off-the-
    shelf part dictates how high it lifts the device. Override only when
    intentionally stacking a non-standard part.
    """

    model_config = ConfigDict(frozen=True)

    connector: str
    height: float | None = None

    def resolved_height(self) -> float:
        if self.height is not None:
            return self.height
        return get_connector(self.connector).standard_height

    def resolved_connector(self) -> Connector:
        return get_connector(self.connector)
