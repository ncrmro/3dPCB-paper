# 3dPCB-paper CAD

Spike CAD for routing an ESP32-C3 + two I2C sensors through a 3D-printed PCB.

## Vitamins (off-the-shelf parts modeled to scale)

- `esp32_c3_supermini` / `esp32_c3_carrier` / `esp32_c3_assembly` — ESP32-C3 Supermini MCU and expansion carrier
- `scd41_breakout` — SCD41 CO2 + temp + humidity (I2C 0x62)
- `bh1750_breakout` — BH1750 ambient light (I2C 0x23)

I2C wiring target: SDA = GPIO5, SCL = GPIO6, 3V3 + GND. Mirrors plant-caravan
so any firmware port is drop-in.

## Develop

```bash
nix develop -c ./bin/render
```

Outputs `.scad` files into `build/`.

Vitamins are copied verbatim from `ncrmro/plant-caravan/hardware/cad/src/vitamins/`
(esp32.py, sensors.py) so future updates can be diffed back.
