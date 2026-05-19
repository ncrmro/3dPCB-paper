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
- **Reference orientation**: USB-C connector facing **+Y** (north),
  J1A on the −X side (left column), J1B on the +X side (right
  column) when viewed from above with silkscreen visible.
- **Pin-1 marker**: on most clones, pin 1 of each row is **closest
  to the USB-C end** (the +Y end of the column). The SuperMini
  README and `code/kicad/gen_spike_pcb.py:29-32` both agree: pins
  run "top to bottom" 1 → 9 with pin 1 at the USB-C end.
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
- **Pin-1 marker**: silkscreen reads
  **"VIN · GND · SCL · SDA"** L→R from the labelled "VIN" pad
  (Adafruit product page diagram, schematic PDF). The substrate
  treats `VIN` as `VCC` (+3V3 from the regulator on the SuperMini).
- **Source / authority**:
  - Adafruit product page: `adafruit.com/product/5190`
  - Adafruit STEMMA QT family pinout convention (VIN, GND, SCL,
    SDA) used across the Adafruit sensor library.
- **PINOUT** (recorded in `vitamins/sensors_pinout.py`):
  - J2: `[VCC, GND, SCL, SDA]`
- **Mismatch flags**: none. (VIN is treated as VCC; the +3V3 rail
  the SuperMini exposes is within the 3.3-5V VIN range listed on
  the Adafruit page.)

## BH1750 — GY-302

- **Module**: GY-302 BH1750 ambient light sensor breakout.
- **Vitamin class**: `Bh1750Dimensions` (`vitamins/sensors.py`).
- **Reference orientation**: 5-pin header J3 on one short edge of
  the board; silkscreen labels printed alongside.
- **Pin-1 marker**: silkscreen reads
  **"VCC · GND · SCL · SDA · ADDR"** L→R, with VCC at the pin-1
  end. The usini KiCad footprint
  (`code/kicad/footprints/usini_sensors.pretty/module_bh1750.kicad_mod`,
  attribution in `data/models/bh1750_breakout/ATTRIBUTION.md`)
  matches: pad 1 is the VCC pad.
- **Source / authority**:
  - `data/models/bh1750_breakout/ATTRIBUTION.md` →
    `usini/usini_kicad_sensors` footprint.
  - Multiple GY-302 product pages (e.g. SparkFun, generic AliExpress
    listings) all show the same silkscreen order.
- **PINOUT** (recorded in `vitamins/sensors_pinout.py`):
  - J3: `[VCC, GND, SCL, SDA, ADDR]`
- **Mismatch flags**: none. ADDR is a sensor-local I2C-address-select
  pin and intentionally NOT a member of `PRIMARY_BUS` (it's tied to
  ground externally to select the 0x23 address).

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
