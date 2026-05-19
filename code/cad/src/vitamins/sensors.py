"""Sensor module dimensions and visual models."""

import anchorscad as ad
from anchorscad import datatree
from dataclasses import field
from typing import Tuple

# Re-export PINOUTs (canonical source: `sensors_pinout.py` — a pure-data
# sibling that doesn't pull anchorscad, so the KiCad flake can also
# import them).
from vitamins.sensors_pinout import BH1750_PINOUT, SCD41_PINOUT  # noqa: F401


@datatree
class Scd41Dimensions:
    """
    SCD41 CO2 sensor breakout module (measured).

    No mounting holes on this breakout board.
    """

    # Breakout PCB dimensions (measured)
    width: float = 13.3  # mm
    depth: float = 21.75  # mm
    pcb_thickness: float = 1.6  # mm

    # Sub-PCB (intermediate board between breakout PCB and sensor chip)
    sub_pcb_width: float = 8.44   # mm
    sub_pcb_depth: float = 8.44   # mm
    sub_pcb_thickness: float = 1.0  # mm
    sub_pcb_offset_y: float = 5.155  # mm — from breakout PCB center toward +Y

    # Actual SCD41 sensor chip (centered on sub-PCB)
    sensor_width: float = 5.5   # mm
    sensor_depth: float = 5.5   # mm
    sensor_height: float = 5.5  # mm — above sub-PCB surface

    # Total height including PCB + sub-PCB + sensor
    @property
    def height(self) -> float:
        return self.pcb_thickness + self.sub_pcb_thickness + self.sensor_height

    # Female header (4-pin I2C header on one edge)
    header_pitch: float = 2.54  # mm
    header_pins: int = 4
    header_plastic_height: float = 2.5  # mm — plastic housing below PCB
    header_total_height: float = 8.0  # mm — total protrusion below PCB (plastic + pins)
    header_body_width: float = 2.54  # mm — single-row header body depth


@datatree
class Bh1750Dimensions:
    """
    BH1750 light sensor breakout module (measured).

    GY-302 breakout board. Two 3mm mounting holes on the end
    opposite the header (+Y side).
    """

    # PCB dimensions (measured)
    width: float = 14.0  # mm
    depth: float = 18.5  # mm
    pcb_thickness: float = 1.6  # mm

    # Sensor IC (small dome/window)
    sensor_width: float = 3.0  # mm
    sensor_depth: float = 3.0  # mm
    sensor_height: float = 2.0  # mm — dome above PCB

    # Total height including PCB
    @property
    def height(self) -> float:
        return self.pcb_thickness + self.sensor_height

    # Mounting holes (3mm, 2 on end opposite header, +Y side)
    hole_diameter: float = 3.0  # mm (measured)
    hole_inset_x: float = 2.0  # mm — from edge
    hole_inset_y: float = 2.0  # mm — from edge

    # Female header (5-pin I2C header on -Y edge)
    header_pitch: float = 2.54  # mm
    header_pins: int = 5
    header_plastic_height: float = 2.5  # mm — plastic housing below PCB
    header_total_height: float = 8.0  # mm — total protrusion below PCB (plastic + pins)
    header_body_width: float = 2.54  # mm — single-row header body depth

    @property
    def mounting_holes(self) -> Tuple[Tuple[float, float], ...]:
        """Returns (x, y) positions of mounting holes relative to PCB center."""
        hw = self.width / 2 - self.hole_inset_x
        hd = self.depth / 2 - self.hole_inset_y
        # 2 holes on end opposite header (+Y side)
        return (
            (-hw, hd),
            (hw, hd),
        )


@ad.shape
@datatree
class Scd41Breakout(ad.CompositeShape):
    """Visual model of SCD41 CO2 sensor breakout board."""

    dim: Scd41Dimensions = field(default_factory=Scd41Dimensions)

    def build(self) -> ad.Maker:
        # Layer 1: Breakout PCB (purple, typical breakout color)
        pcb = ad.Box([self.dim.width, self.dim.depth, self.dim.pcb_thickness])

        # Layer 2: Sub-PCB (intermediate board, dark gray)
        sub_pcb = ad.Box([
            self.dim.sub_pcb_width,
            self.dim.sub_pcb_depth,
            self.dim.sub_pcb_thickness,
        ])

        # Layer 3: Actual SCD41 sensor chip (black, centered on sub-PCB)
        sensor = ad.Box([
            self.dim.sensor_width,
            self.dim.sensor_depth,
            self.dim.sensor_height,
        ])

        # Build assembly
        shape = pcb.solid("pcb").colour([0.4, 0.2, 0.5]).at("centre")

        # Add sub-PCB on top of breakout PCB, offset toward +Y
        sub_pcb_z = self.dim.pcb_thickness / 2 + self.dim.sub_pcb_thickness / 2
        shape.add_at(
            sub_pcb.solid("sub_pcb").colour([0.25, 0.25, 0.25]).at("centre"),
            post=ad.translate([0, self.dim.sub_pcb_offset_y, sub_pcb_z]),
        )

        # Add sensor chip centered on sub-PCB
        sensor_z = (
            self.dim.pcb_thickness / 2
            + self.dim.sub_pcb_thickness
            + self.dim.sensor_height / 2
        )
        shape.add_at(
            sensor.solid("sensor_ic").colour([0.1, 0.1, 0.1]).at("centre"),
            post=ad.translate([0, self.dim.sub_pcb_offset_y, sensor_z]),
        )

        # Add female header below PCB at front edge (-Y)
        header_width = self.dim.header_pins * self.dim.header_pitch
        header_y = -self.dim.depth / 2 + self.dim.header_body_width / 2  # front edge
        header_plastic = ad.Box([
            header_width,
            self.dim.header_body_width,
            self.dim.header_plastic_height,
        ])
        header_pins_block = ad.Box([
            header_width,
            self.dim.header_body_width,
            self.dim.header_total_height - self.dim.header_plastic_height,
        ])
        # Plastic housing flush against PCB bottom
        plastic_z = -self.dim.pcb_thickness / 2 - self.dim.header_plastic_height / 2
        shape.add_at(
            header_plastic.solid("header_plastic").colour([0.15, 0.15, 0.15]).at("centre"),
            post=ad.translate([0, header_y, plastic_z]),
        )
        # Pins extend below plastic (silver)
        pins_height = self.dim.header_total_height - self.dim.header_plastic_height
        pins_z = -self.dim.pcb_thickness / 2 - self.dim.header_plastic_height - pins_height / 2
        shape.add_at(
            header_pins_block.solid("header_pins").colour([0.75, 0.75, 0.8]).at("centre"),
            post=ad.translate([0, header_y, pins_z]),
        )

        return shape


@ad.shape
@datatree
class Bh1750Breakout(ad.CompositeShape):
    """Visual model of BH1750 light sensor breakout board."""

    dim: Bh1750Dimensions = field(default_factory=Bh1750Dimensions)

    def build(self) -> ad.Maker:
        # Main PCB (blue, typical GY-302 color)
        pcb = ad.Box([self.dim.width, self.dim.depth, self.dim.pcb_thickness])

        # Light sensor dome (translucent white)
        sensor = ad.Cylinder(
            r=self.dim.sensor_width / 2,
            h=self.dim.sensor_height,
        )

        # Build assembly
        shape = pcb.solid("pcb").colour([0.1, 0.2, 0.6]).at("centre")

        # Add sensor dome centered on PCB
        sensor_z = self.dim.pcb_thickness / 2 + self.dim.sensor_height / 2
        shape.add_at(
            sensor.solid("sensor_dome").colour([0.9, 0.9, 0.95, 0.8]).at("centre"),
            post=ad.translate([0, 0, sensor_z]),
        )

        # Add female header below PCB at front edge (-Y)
        header_width = self.dim.header_pins * self.dim.header_pitch
        header_y = -self.dim.depth / 2 + self.dim.header_body_width / 2  # front edge
        header_plastic = ad.Box([
            header_width,
            self.dim.header_body_width,
            self.dim.header_plastic_height,
        ])
        header_pins_block = ad.Box([
            header_width,
            self.dim.header_body_width,
            self.dim.header_total_height - self.dim.header_plastic_height,
        ])
        # Plastic housing flush against PCB bottom
        plastic_z = -self.dim.pcb_thickness / 2 - self.dim.header_plastic_height / 2
        shape.add_at(
            header_plastic.solid("header_plastic").colour([0.15, 0.15, 0.15]).at("centre"),
            post=ad.translate([0, header_y, plastic_z]),
        )
        # Pins extend below plastic (silver)
        pins_height = self.dim.header_total_height - self.dim.header_plastic_height
        pins_z = -self.dim.pcb_thickness / 2 - self.dim.header_plastic_height - pins_height / 2
        shape.add_at(
            header_pins_block.solid("header_pins").colour([0.75, 0.75, 0.8]).at("centre"),
            post=ad.translate([0, header_y, pins_z]),
        )

        # Add mounting holes
        hole = ad.Cylinder(
            r=self.dim.hole_diameter / 2,
            h=self.dim.pcb_thickness + 0.2,
        )
        for i, (hx, hy) in enumerate(self.dim.mounting_holes):
            shape.add_at(
                hole.hole(f"mount_hole_{i}").at("centre"),
                post=ad.translate([hx, hy, 0]),
            )

        return shape
