"""Declarative board primitives.

A `Board` is the user-facing object: a base plate plus a list of placed
devices (microcontrollers + sensors) wired together by one or more buses.
The router takes the resolved nets and the builder turns the result into
a 3D-printable substrate.

Public types are re-exported here so callers do `from board import Board, …`.
"""

from board.board import Board, DeviceInstance, Level, Point2D, Rect
from board.buses import Bus, Net
from board.connectors import CONNECTOR_REGISTRY, Connector
from board.devices import (
    DEVICE_REGISTRY,
    Device,
    Microcontroller,
    Sensor,
    register_device,
)
from board.loader import dump_board, load_board
from board.mounts import Header
from board.pins import Pin, PinGroup

# Importing the device library registers every concrete device into
# DEVICE_REGISTRY at module import time. Importers of `board` get a
# populated registry without having to know about the per-device files.
from board import device_library  # noqa: F401
# spec_discovery walks specs/*.yaml and synthesises an AnchorSCAD
# Shape subclass per Board so the render pipeline finds them.
from board import spec_discovery  # noqa: F401

__all__ = [
    "Board",
    "Bus",
    "Connector",
    "CONNECTOR_REGISTRY",
    "DEVICE_REGISTRY",
    "Device",
    "DeviceInstance",
    "Header",
    "Level",
    "Microcontroller",
    "Net",
    "Pin",
    "PinGroup",
    "Point2D",
    "Rect",
    "Sensor",
    "dump_board",
    "load_board",
    "register_device",
]
