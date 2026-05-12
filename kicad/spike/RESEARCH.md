# Spike PCB: open-source asset research

Date: 2026-05-11
Status: findings recorded, sources not yet imported

## Mounting recommendation

**Female 1x4 / 1x5 / 1x9 headers for all three modules.** A research-paper spike is throwaway-by-design; reworkability when a single breakout fails (or pinout turns out to be a clone variant) outweighs the ~$1 in headers. SCD41 vendor pin orders vary, BH1750 ADDR/SDA can be swapped on clones, and the Supermini has multiple GPIO-numbering revisions — soldering directly to castellated edges locks in those risks.

## Per-module recommendations

**ESP32-C3 Supermini.** No official Espressif KiCad asset exists for the third-party "Supermini" form factor — the `espressif/kicad-libraries` repo only covers Espressif's own DevKits and bare modules. The best community asset is `mrtnvgr/KiCad_ESP32-C3-SuperMini`, which ships symbol, `.pretty` footprint and `.stp`; license is **unstated in the repo**, treat as all-rights-reserved until clarified. SnapEDA also publishes both a TH and SMD variant (free download, SnapEDA terms allow redistribution in personal/commercial designs but not re-hosting the library itself). Use SnapEDA for the spike unless we can get an MIT/CC0 commitment from mrtnvgr.

**Sensirion SCD41.** The official KiCad v8 `Sensor_Gas` library contains `SCD40-D-R2` (same footprint and pinout as SCD41 per Sensirion datasheet) — canonical bare-IC choice, CC-BY-SA 4.0 with the KiCad library exception. However, we are not mounting the bare IC; we are mounting an Adafruit STEMMA QT 5190 or generic GY-SCD41 breakout, which means the relevant "footprint" is just a 1x4 (Adafruit) or 1x4-with-vendor-variant pin header. Use `Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical` from the KiCad standard library and silkscreen the breakout outline manually — **flag SDA/SCL/VCC/GND order on the BOM** since Adafruit, DFRobot and AliExpress GY-SCD41 differ.

**Rohm BH1750 / GY-302.** Same pattern: the bare BH1750FVI is in KiCad's `Sensor` library, but for the GY-302 breakout the right approach is a 1x5 header (VCC/GND/SCL/SDA/ADDR) plus silkscreen outline. `usini/usini_kicad_sensors` explicitly ships a GY-302-module footprint and is CC-0 — preferred source. `LaskaKit/BH1750-Ambient-Light-Sensor` is their own uSup-connector variant, not the GY-302, so not useful here.

## Links table

| Module | Asset | URL | License |
|---|---|---|---|
| ESP32-C3 Supermini | Symbol + FP + STEP | https://github.com/mrtnvgr/KiCad_ESP32-C3-SuperMini | unstated (FLAG) |
| ESP32-C3 Supermini | Symbol + FP + STEP | https://www.snapeda.com/parts/ESP32-C3%20SuperMini_TH/Espressif%20Systems/view-part/ | SnapEDA ToS |
| Espressif official lib (reference) | Symbols/FP/STEP | https://github.com/espressif/kicad-libraries | Apache-2.0 (no Supermini) |
| SCD41 (bare IC) | Symbol | KiCad stdlib `Sensor_Gas:SCD40-D-R2` | CC-BY-SA 4.0 + lib exception |
| SCD41 (vendor) | Symbol + FP + STEP | https://www.snapeda.com/parts/SCD41-D-R2/Sensirion/view-part/ | SnapEDA ToS |
| SCD41 (vendor) | Symbol + FP + STEP | https://app.ultralibrarian.com/details/80669ae7-eefb-11ed-b159-0a34d6323d74/Sensirion/SCD41-D-R2 | UL ToS |
| BH1750 GY-302 | Symbol + FP (module) | https://github.com/usini/usini_kicad_sensors | CC-0 |
| BH1750FVI (bare IC) | Symbol + FP + STEP | https://www.snapeda.com/parts/BH1750FVI-TR/Rohm/view-part/ | SnapEDA ToS |
| Headers (used for all breakouts) | FP | KiCad stdlib `Connector_PinHeader_2.54mm` | CC-BY-SA 4.0 + lib exception |

## Existing projects to consider forking

- **https://github.com/Loufe/esp32-c3-supermini-scd41-esphome** — ESPHome YAML only, no KiCad. Useful as a wiring reference (uses GPIO3=SDA, GPIO4=SCL on its Supermini — note this differs from our GPIO5/6 target inherited from plant-caravan). **No LICENSE file** — firmware-only so this only matters if we copy YAML.
- **https://github.com/21km43/ESP32-C3-DevBoard** — KiCad 9 project using Espressif's official lib; bare-chip design, not Supermini, but a clean reference for the I2C wiring pattern.
- **https://github.com/EObianom/ESP32-C3_supermini** — Schematic / PCB / gerbers for a bare-chip Supermini clone (i.e. building the Supermini from scratch). Not a fork target for a sensor node, but useful if we ever pivot to a single-board design. License unclear.

No GitHub project was found that combines all three modules in a single KiCad design. Closest is Loufe (Supermini + SCD41, firmware-only).

## License flags

- **mrtnvgr/KiCad_ESP32-C3-SuperMini**: no LICENSE file — must email author for explicit MIT/CC0/CC-BY before publishing the derived board, or fall back to SnapEDA.
- **SnapEDA / Ultra Librarian**: free to use in designs (incl. commercial) but **the libraries themselves cannot be re-hosted** in our repo; consumers must re-download. Document the part IDs in the BOM instead of committing the `.kicad_sym` / `.kicad_mod` to the repo.
- **Loufe ESPHome YAML**: unlicensed; treat as all-rights-reserved if we copy any YAML verbatim.
- **EObianom, 21km43**: license unstated — reference only, do not fork into a permissively-licensed publication.
- **KiCad official libraries**: CC-BY-SA 4.0 with an explicit library exception allowing use in any-licensed design without copyleft propagation — fully compatible with MIT / Apache / CC-BY / CERN-OHL publication.
- **usini/usini_kicad_sensors**: CC-0 — fully compatible.
- **Espressif kicad-libraries**: Apache-2.0 — fully compatible.

**Net**: a fully permissive publication is achievable if we (a) use the KiCad-official `SCD40-D-R2` symbol referenced via 1x4 header, (b) use usini's GY-302 module footprint, and (c) reference the Supermini via SnapEDA part number in the BOM without committing its files — or get explicit licensing from mrtnvgr.
