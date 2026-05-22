# Breakout-pinout audit

Documents the silkscreen-to-footprint mapping that justifies each
`<NAME>_PINOUT` declaration in `vitamins/esp32_pinout.py` and
`vitamins/sensors_pinout.py`.

The tests in `tests/test_netlist.py` enforce internal consistency
between the netlist and the AnchorSCAD geometry. They CANNOT catch
a wrong silkscreen attribution — that's a one-time human check
against vendor docs, recorded here. If a sensor is ever swapped
for a different breakout, update the matching `_PINOUT` and this
audit entry together.

Date of audit: **2026-05-18**. Auditor: Nicholas Romero.

---

## ESP32-C3 SuperMini

- **Module**: ESP32-C3 SuperMini (generic clone, 8/9-pin castellated
  rows). Sourced from `mrtnvgr/esp32_supermini` 3D model.
- **Vitamin class**: `Esp32C3SuperminiDimensions`
  (`vitamins/esp32.py`).
- **Reference orientation**: USB-C connector facing **−Y** (south
  on the substrate), J1A on the −X side (west / "left" column),
  J1B on the +X side (east / "right" column) when viewed from
  above with the silkscreen visible. The board is component-side
  up. This orientation is what makes J1A the power column
  (+5V/GND/+3V3) on the substrate: per the plant-caravan SuperMini
  ASCII pinout (the authoritative source, at
  `~/repos/ncrmro/plant-caravan/hardware/docs/ESP32-C3-SuperMini.md`),
  the power column sits opposite the USB-C-relative-right side, so
  USB-C-south + component-up places power on the substrate's west.
  Earlier audit revisions declared USB-C facing +Y — that was
  inconsistent with the recorded J1A=power PINOUT and was caught
  by a "GND is second from back-left" inspection of the rendered
  substrate.
- **Pin-1 marker**: pin 1 of each row is **closest to the USB-C
  end** (the −Y end of the column on this substrate). The
  SuperMini README and `code/kicad/gen_spike_pcb.py:29-32` both
  agree: pins run 1 → 9 with pin 1 at the USB-C end.
- **Source / authority**:
  - `data/models/esp32_c3_supermini/ATTRIBUTION.md` →
    `mrtnvgr/esp32_supermini` README (commit pinned in
    `bin/fetch-models`).
  - ESP32-C3 SuperMini pinout image (multiple vendor pages agree
    on GPIO assignments).
- **PINOUT** (recorded in `vitamins/esp32_pinout.py`):
  - J1A: `[+5V, GND, +3V3, GPIO4, GPIO3, GPIO2, GPIO1, GPIO0, NC]`
  - J1B: `[GPIO5=SDA, GPIO6=SCL, GPIO7, GPIO8, GPIO9, GPIO10,
    GPIO20, GPIO21, NC2]`
- **Mismatch flags**: none.

## SCD41 — Adafruit STEMMA QT 5190

- **Module**: Adafruit SCD-41 True CO2, Temperature and Humidity
  Sensor breakout, part #5190.
- **Vitamin class**: `Scd41Dimensions` (`vitamins/sensors.py`).
- **Reference orientation**: 4-pin header J2 on the long edge of
  the board; silkscreen labels visible adjacent to each pad.
- **Pin-1 marker**: silkscreen on the physical breakout in hand
  reads **"GND · VIN · SCL · SDA"** L→R (confirmed 2026-05-19 by
  inspection of the populated unit). Earlier versions of this
  audit recorded `VIN · GND` from the Adafruit product-page
  diagram; the physical board's silkscreen runs the rails in the
  opposite order. The substrate treats `VIN` as `VCC` (+3V3 from
  the regulator on the SuperMini).
- **Source / authority**:
  - Physical board silkscreen (Adafruit 5190, ordered 2026-05).
  - Adafruit product page: `adafruit.com/product/5190` — note
    the on-page diagram showed the rails in the reversed
    orientation relative to the silkscreen on the unit shipped.
- **PINOUT** (recorded in `vitamins/sensors_pinout.py`):
  - J2: `[GND, VCC, SCL, SDA]`
- **Mismatch flags**: previous version of the PINOUT had pin 1 =
  VCC, pin 2 = GND from the product-page diagram. Corrected
  2026-05-19 after physical-board silkscreen audit.

## BH1750 — GY-302

- **Module**: GY-302 BH1750 ambient light sensor breakout.
- **Vitamin class**: `Bh1750Dimensions` (`vitamins/sensors.py`).
- **Reference orientation**: 5-pin header J3 on one short edge of
  the board; silkscreen labels printed alongside.
- **Silkscreen order** (reading L→R when display IC is upright):
  **`VCC · GND · SCL · SDA · ADDR`**.
- **MISMATCH — footprint pad numbering is reversed**: the usini
  KiCad footprint (`data/models/bh1750_breakout/module_bh1750.kicad_mod`)
  numbers its pads in the OPPOSITE order to the silkscreen:
  ```
  pad 1 at (0, -10.16)  →  silkscreen ADDR
  pad 2 at (0,  -7.62)  →  silkscreen SDA
  pad 3 at (0,  -5.08)  →  silkscreen SCL
  pad 4 at (0,  -2.54)  →  silkscreen GND
  pad 5 at (0,   0.00)  →  silkscreen VCC
  ```
  The footprint's `(fp_text user <NAME> ...)` lines and the
  numbered `(pad N ...)` lines confirm this: pad N's coordinates
  sit at the silkscreen label of the OTHER-END pin.
- **PINOUT consequence** (recorded in `vitamins/sensors_pinout.py`):
  the PINOUT follows the FOOTPRINT pad numbers (because
  `_pin_position(Pin("J3", N))` resolves to the footprint pad-N
  location), NOT the silkscreen reading order:
  - J3.1 = ADDR
  - J3.2 = SDA
  - J3.3 = SCL
  - J3.4 = GND
  - J3.5 = VCC
- **Confirmed via**: physical inspection of the populated substrate
  (the v1/v2 STL had the bus signals wired to the wrong physical
  pins, with VCC reaching the ADDR pin and so on; reversing the
  PINOUT corrects this without any geometry change).
- **Source / authority**:
  - `data/models/bh1750_breakout/ATTRIBUTION.md` →
    `usini/usini_kicad_sensors` footprint.
  - Multiple GY-302 product pages confirm the silkscreen order.
- **ADDR usage**: ADDR is a sensor-local I2C-address-select pin and
  intentionally NOT a member of `PRIMARY_BUS` (it's tied to ground
  externally to select the 0x23 address).

---

## How to re-run the audit

1. With each breakout in hand, photograph the silkscreen and confirm
   the pin-1 marker matches the vendor page.
2. Open the corresponding `.kicad_mod` footprint (under
   `code/kicad/footprints/` or `data/models/<module>/`) and confirm
   pad 1's position relative to the silkscreen orientation.
3. If a mismatch is found:
   - Edit the matching `<NAME>_PINOUT` to compensate (swap pin
     numbers so the netlist Pin's `number` field points at the
     correct physical pad).
   - Update this audit document with a `MISMATCH:` entry and the
     date / reason.
   - `bin/test` will fail until the netlist tests still agree
     internally — a mismatch fix is mechanical from there.
