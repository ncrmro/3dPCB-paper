"""Small test coupon for dialing in the OLED pressure-fit receptacle.

Prints a flat plate with several rows of 4 receptacles each, every
row at a slightly different hole diameter, so one print lets you
compare fits against a real OLED's male header (or a standalone 0.64
mm DuPont pin). Each row has a bottom-face L1 channel connecting its
4 receptacles, mirroring how the Tier 2 substrate routes wire to the
pin tips on the underside — so you can also test threading copper
wire through the receptacle and confirming electrical contact with a
seated pin.

⚠ Empirical observation (2026-05-19, Bambu Studio defaults, 0.4 mm
nozzle): designed hole diameters below ~0.7 mm DO NOT print as
through-holes — the slicer / printer closes them entirely. The
original 0.50–0.65 mm coupon produced ZERO holes that light could
pass through. See `docs/fdm_tolerance_notes.md` for the full
measurements. The current defaults (0.80, 0.95, 1.10, 1.25 mm) are
chosen to bracket a likely-printable range; YOUR printer may need
the values shifted.

Suggested workflow:
1. Slice + print this coupon. Default size is ~20 × 30 × 3 mm.
2. Check the printed holes are open — hold the coupon up to a light
   source and confirm each row's 4 holes pass light. If a row is
   closed, you need to bump that row's diameter upward in CAD.
3. Press a single OLED header pin (or DuPont jumper) into each open
   row in turn. Note which diameter grips with a satisfying "click"
   but lets the pin still seat fully (~3 mm flush).
4. Lay a length of bare 22 AWG copper wire in the bottom-face channel
   of that row. Confirm the wire makes physical contact with the pin
   tip protruding below the receptacle.
5. Update `Tier1SubstrateDimensions.receptacle_diameter` in
   `vitamins/substrate.py` to the winning value, then re-render
   `tier2_substrate` for the real print.

If no row produces a snug fit, iterate: edit `diameters` below to
shift the test range and re-print.
"""

from dataclasses import field

import anchorscad as ad
from anchorscad import datatree


@datatree
class ReceptacleTestCouponDimensions:
    """Test-coupon geometry."""

    # Plate footprint (mm).
    width: float = 20.0     # x extent
    depth: float = 30.0     # y extent
    thickness: float = 3.0  # z, matches the substrate thickness

    # Receptacle diameters to compare. One row per entry.
    #
    # 2026-05-19 v2: the original 0.50–0.65 mm range printed as solid
    # plastic (no through-holes resolved at all) under default Bambu
    # Studio settings on a 0.4 mm nozzle. New defaults shift up to a
    # range where small through-holes are reliably resolved.
    # See `docs/fdm_tolerance_notes.md` for the empirical data.
    diameters: tuple[float, ...] = (0.80, 0.95, 1.10, 1.25)

    # Pin layout per row (matches an OLED 4-pin 2.54 mm header).
    pin_pitch: float = 2.54
    pins_per_row: int = 4

    # Row spacing in y (mm). Wider than the OLED header pitch so it's
    # easy to identify rows by eye.
    row_pitch: float = 6.0

    # Bottom-face channel that connects the 4 receptacles in each row.
    # Matches the substrate's default channel cross-section.
    channel_width: float = 0.8
    channel_depth: float = 0.8

    overcut: float = 0.1


@ad.shape
@datatree
class ReceptacleTestCoupon(ad.CompositeShape):
    """Test coupon for OLED-pin pressure-fit + copper-wire-in-channel.

    Prints a small flat plate with `len(dim.diameters)` rows of 4
    receptacles each. Each row's bottom face carries an L1 channel
    connecting its 4 receptacles so you can also test the
    wire-meets-pin-tip mechanism.
    """

    dim: ReceptacleTestCouponDimensions = field(
        default_factory=ReceptacleTestCouponDimensions
    )

    def build(self) -> ad.Maker:
        d = self.dim

        plate = ad.Box([d.width, d.depth, d.thickness])
        shape = plate.solid("plate").colour([0.92, 0.88, 0.78]).at("centre")

        # L1 channel z: cut INTO the bottom face. Mirrors substrate.py.
        l1_z = -d.thickness / 2 + d.channel_depth / 2 - d.overcut / 2

        # Centre rows in y, pins in x.
        rows = len(d.diameters)
        y_first = -(rows - 1) * d.row_pitch / 2
        row_pin_span = (d.pins_per_row - 1) * d.pin_pitch
        x_first = -row_pin_span / 2

        for row_idx, diameter in enumerate(d.diameters):
            y = y_first + row_idx * d.row_pitch

            # Receptacle cylinder for this row's diameter.
            receptacle = ad.Cylinder(
                r=diameter / 2, h=d.thickness + 0.4
            )

            # 4 receptacle through-holes at 2.54 mm pitch.
            for pin_idx in range(d.pins_per_row):
                x = x_first + pin_idx * d.pin_pitch
                shape.add_at(
                    receptacle.hole(f"r{row_idx}_p{pin_idx}").at("centre"),
                    post=ad.translate([x, y, 0]),
                )

            # Bottom-face channel along this row, connecting all 4
            # receptacles. Length matches the pin span; channel cuts
            # into the bottom of the plate.
            channel = ad.Box([
                row_pin_span + d.overcut,
                d.channel_width,
                d.channel_depth + d.overcut,
            ])
            shape.add_at(
                channel.hole(f"channel_r{row_idx}").at("centre"),
                post=ad.translate([0, y, l1_z]),
            )

        return shape
