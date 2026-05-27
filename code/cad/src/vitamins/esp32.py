"""ESP32 component dimensions and visual models."""

from dataclasses import field

import anchorscad as ad
from anchorscad import datatree

from registry import register_part


@datatree
class Esp32C3SuperminiDimensions:
    """ESP32-C3 SuperMini MCU module dimensions.

    User-provided measurements:
    - Width: 18mm
    - Length: 22.5mm
    - Pin gap: 2.54mm (standard header pitch)
    """

    width: float = 18.0  # mm — user measured
    length: float = 22.5  # mm — user measured
    pcb_thickness: float = 1.5  # mm — user measured on the variant in hand
    pin_pitch: float = 2.54  # mm — standard header pitch
    pin_rows: int = 2  # rows of pins (left and right)
    pins_per_row: int = 8  # pins per side

    # ESP32-C3 chip (main MCU IC)
    chip_width: float = 5.0  # mm — user measured
    chip_height: float = 1.0  # mm — above PCB (1.8mm total including 0.8mm PCB)

    # USB-C connector (4mm total including 0.8mm PCB = 3.2mm above PCB)
    usb_c_width: float = 9.0  # mm
    usb_c_height: float = 3.2  # mm — above PCB surface (4mm total with PCB)
    usb_c_depth: float = 7.0  # mm
    usb_c_overhang: float = 1.5  # mm past PCB edge

    # Pin header dimensions
    pin_header_height: float = 8.0  # mm — soldered male header below PCB

    @property
    def total_height(self) -> float:
        """Total height including chip (above PCB bottom)."""
        return self.pcb_thickness + self.chip_height

    @property
    def total_height_with_headers(self) -> float:
        """Total height from bottom of soldered headers to top of USB-C.

        User measured: 12mm total
        """
        return self.pin_header_height + self.pcb_thickness + self.usb_c_height

    @property
    def pin_inset(self) -> float:
        """Distance from PCB edge to pin row center."""
        return 1.27  # mm — half of 2.54mm pitch


@datatree
class Esp32C3CarrierDimensions:
    """ESP32-C3 SuperMini Expansion Board (carrier) — VERIFIED from docs.

    Source: hardware/docs/ESP32-C3-SuperMini-Expansion-Board.md
    "Compact Size: Measures only 37.4mm x 22.5mm x 15.2mm"
    """

    width: float = 37.4  # mm — documented
    depth: float = 22.5  # mm — documented
    height: float = 15.2  # mm — documented (includes seated MCU)
    pcb_thickness: float = 1.6  # mm — standard PCB

    # Female header sockets for MCU (user measured)
    socket_height: float = 8.2  # mm — user measured
    socket_width: float = 2.5  # mm — user measured
    socket_length: float = 20.6  # mm — user measured, starts from exact back
    socket_pitch: float = 2.54  # mm

    # JST battery connector (at back)
    jst_width: float = 8.0  # mm
    jst_height: float = 4.5  # mm
    jst_depth: float = 6.0  # mm

    # Mounting holes (on front, inside headers)
    hole_inset_x: float = 14.0  # mm from left/right edges
    hole_inset_y: float = 2.5  # mm from front edge
    hole_diameter: float = 2.5  # mm — M2.5 mounting holes (VERIFY)

    # Header pins protruding below carrier PCB (through-hole solder joints)
    header_protrusion: float = 1.6  # mm — measured, pins stick out bottom

    @property
    def mcu_seat_height(self) -> float:
        """Height where MCU PCB bottom sits (top of female headers)."""
        return self.pcb_thickness + self.socket_height


@ad.shape
@datatree
class Esp32C3Supermini(ad.CompositeShape):
    """Visual model of ESP32-C3 SuperMini MCU module."""

    dim: Esp32C3SuperminiDimensions = field(default_factory=Esp32C3SuperminiDimensions)

    def build(self) -> ad.Maker:
        # Main PCB
        pcb = ad.Box([self.dim.width, self.dim.length, self.dim.pcb_thickness])

        # ESP32-C3 chip on top of PCB (dark gray IC package)
        chip = ad.Box([
            self.dim.chip_width,
            self.dim.chip_width,  # Square chip
            self.dim.chip_height,
        ])

        # USB-C connector
        usb_c = ad.Box([
            self.dim.usb_c_width,
            self.dim.usb_c_depth,
            self.dim.usb_c_height,
        ])

        # Pin headers (simplified as boxes on each side)
        pin_header = ad.Box([
            1.0,  # Thin strip
            self.dim.length - 4.0,  # Most of length
            self.dim.pin_header_height,
        ])

        # Build assembly - black PCB
        shape = pcb.solid("pcb").colour("black").at("centre")

        # Add chip on top of PCB (dark gray IC package, rotated 45 degrees)
        # USB-C is at back (+Y), chip is 4mm from front edge (-Y)
        chip_z = self.dim.pcb_thickness / 2 + self.dim.chip_height / 2
        chip_y = -self.dim.length / 2 + 4.0  # 4mm from front edge
        shape.add_at(
            chip.solid("chip").colour([0.15, 0.15, 0.15]).at("centre"),
            post=ad.translate([0, chip_y, chip_z]) * ad.rotZ(45),
        )

        # Add USB-C at front edge (silver metal)
        usb_y = self.dim.length / 2 + self.dim.usb_c_overhang - self.dim.usb_c_depth / 2
        usb_z = self.dim.pcb_thickness / 2 + self.dim.usb_c_height / 2
        shape.add_at(
            usb_c.solid("usb_c").colour([0.75, 0.75, 0.8]).at("centre"),
            post=ad.translate([0, usb_y, usb_z]),
        )

        # Add pin headers below PCB (gold pins)
        pin_z = -self.dim.pcb_thickness / 2 - self.dim.pin_header_height / 2
        pin_x_offset = self.dim.width / 2 - self.dim.pin_inset - 0.5

        shape.add_at(
            pin_header.solid("pins_left").colour([0.8, 0.7, 0.2]).at("centre"),
            post=ad.translate([-pin_x_offset, 0, pin_z]),
        )
        shape.add_at(
            pin_header.solid("pins_right").colour([0.8, 0.7, 0.2]).at("centre"),
            post=ad.translate([pin_x_offset, 0, pin_z]),
        )

        return shape


@ad.shape
@datatree
class Esp32C3Carrier(ad.CompositeShape):
    """Visual model of ESP32-C3 SuperMini Expansion Board (carrier)."""

    dim: Esp32C3CarrierDimensions = field(default_factory=Esp32C3CarrierDimensions)

    def build(self) -> ad.Maker:
        # Main PCB
        pcb = ad.Box([self.dim.width, self.dim.depth, self.dim.pcb_thickness])

        # Female header sockets (where MCU plugs in) - user measured
        socket = ad.Box([
            self.dim.socket_width,   # 2.5mm wide
            self.dim.socket_length,  # 20.6mm long
            self.dim.socket_height,  # 8.2mm tall
        ])

        # JST battery connector
        jst = ad.Box([self.dim.jst_width, self.dim.jst_depth, self.dim.jst_height])

        # Build assembly - black PCB
        shape = pcb.solid("pcb").colour("black").at("centre")

        # Add female sockets on top of PCB (muted green)
        # Sockets start from back of board (+Y, same side as USB-C)
        socket_z = self.dim.pcb_thickness / 2 + self.dim.socket_height / 2
        socket_y = self.dim.depth / 2 - self.dim.socket_length / 2  # Start from back (+Y)
        socket_x_offset = 8.0  # Position for 18mm wide MCU pins

        shape.add_at(
            socket.solid("socket_left").colour([0.4, 0.7, 0.3]).at("centre"),
            post=ad.translate([-socket_x_offset, socket_y, socket_z]),
        )
        shape.add_at(
            socket.solid("socket_right").colour([0.4, 0.7, 0.3]).at("centre"),
            post=ad.translate([socket_x_offset, socket_y, socket_z]),
        )

        # Add JST connector at back (+Y, under USB-C area, white plastic)
        jst_y = self.dim.depth / 2 - self.dim.jst_depth / 2
        jst_z = self.dim.pcb_thickness / 2 + self.dim.jst_height / 2
        shape.add_at(
            jst.solid("jst_battery").colour([0.9, 0.9, 0.85]).at("centre"),
            post=ad.translate([0, jst_y, jst_z]),
        )

        # Mounting holes on front (-Y), inside headers
        hole = ad.Cylinder(
            r=self.dim.hole_diameter / 2,
            h=self.dim.pcb_thickness + 0.2,  # Slight overcut for clean hole
        )
        hole_x = self.dim.width / 2 - self.dim.hole_inset_x  # 14mm from edge
        hole_y = -self.dim.depth / 2 + self.dim.hole_inset_y  # 2.5mm from front

        shape.add_at(
            hole.hole("hole_left").at("centre"),
            post=ad.translate([-hole_x, hole_y, 0]),
        )
        shape.add_at(
            hole.hole("hole_right").at("centre"),
            post=ad.translate([hole_x, hole_y, 0]),
        )

        return shape

    @ad.anchor("mcu_seat")
    def mcu_seat(self):
        """Anchor where MCU bottom sits (top of female headers)."""
        z = self.dim.mcu_seat_height
        return ad.translate([0, 0, z])


@ad.shape
@datatree
class Esp32C3Assembly(ad.CompositeShape):
    """Complete assembly: MCU seated in carrier board."""

    carrier_dim: Esp32C3CarrierDimensions = field(default_factory=Esp32C3CarrierDimensions)
    mcu_dim: Esp32C3SuperminiDimensions = field(default_factory=Esp32C3SuperminiDimensions)
    explode: float = 0.0  # mm — vertical separation for exploded view

    def build(self) -> ad.Maker:
        carrier = Esp32C3Carrier(dim=self.carrier_dim)
        mcu = Esp32C3Supermini(dim=self.mcu_dim)

        # Start with carrier
        shape = carrier.solid("carrier").at("centre")

        # Add MCU seated on carrier (with optional explode offset)
        # MCU bottom (where pins end) sits at carrier's mcu_seat height
        mcu_z = self.carrier_dim.mcu_seat_height + self.mcu_dim.pcb_thickness / 2 + self.explode
        shape.add_at(
            mcu.solid("mcu").at("centre"),
            post=ad.translate([0, 0, mcu_z]),
        )

        return shape


# Factory function for exploded view
@register_part("esp32_c3_assembly_exploded", part_type="vitamin")
def esp32_c3_assembly_exploded():
    """ESP32-C3 Assembly with exploded view (30mm separation)."""
    return Esp32C3Assembly(explode=30.0)
