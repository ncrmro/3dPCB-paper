# FDM tolerance notes — small-hole printability

Empirical observations from printing the substrate + receptacle test
coupons on a 0.4 mm-nozzle FDM printer. These numbers drive the
default values in `code/cad/src/vitamins/substrate.py` and
`code/cad/src/vitamins/receptacle_test_coupon.py`.

## Plant-caravan enclosure base — 2026-02-24

PLA, default Bambu Studio settings.

| Feature | CAD (mm) | Printed (mm) | Delta (mm) | Notes |
|---|---|---|---|---|
| Exterior width (Y) | 43.40 | 43.35 | −0.05 | Walls look smooth |
| Interior width | 39.40 | 39.35 | −0.05 | Consistent with exterior shrink |
| Lip recess interior | 42.40 | 42.34 | −0.06 |  |
| Lip recess exterior | 43.40 | 43.83 | **+0.43** | Excess material on outer edge |

**Key finding**: The printer adds excess material (~0.4 mm) at the lip
recess exterior — likely elephant's foot at the recess transition, an
over-extrusion at the layer where the recess begins, or a slicer
seam/overlap artifact. Interior dimensions shrink only marginally
(~0.05 mm).

**Impact on receptacle design**: a small designed hole near a
top-shelf transition can lose substantially more than the −0.05 mm
shrinkage suggests — at the worst-case +0.43 mm over-extrusion, a
0.6 mm designed hole has ~0.17 mm or less of clear bore left, which
the slicer often closes entirely.

## Receptacle test coupon v1 — 2026-05-19

`ReceptacleTestCoupon` with default diameters (0.50, 0.55, 0.60,
0.65 mm). PLA, default Bambu Studio settings.

**Result**: **no rows produced visible through-holes** — light could
not be passed through any receptacle. Consistent with the
above: 0.4 mm-nozzle FDM with default elephant's-foot / seam settings
cannot reliably resolve through-holes below ~0.7–0.8 mm CAD diameter.

## Working assumptions going forward

- **Minimum reliable CAD hole diameter**: ~0.8 mm. Below that, expect
  the slicer to fill or partially close the hole.
- **Interference-fit budget**: aim for ~0.6–0.65 mm *printed* bore
  diameter (so a standard 0.64 mm DuPont pin presses in with grip).
  Working back through the −0.05 mm shrinkage observation, that's
  a CAD design of ~0.65–0.7 mm — but the actual printability depends
  on whether the slicer respects holes that small.
- **Practical recommendation**: design CAD holes 0.85–1.25 mm and
  test which one prints to a usable interference fit on YOUR printer.
  The relationship between CAD and printed dimensions is
  printer-dependent and slicer-setting-dependent; this coupon is the
  measurement tool.

## Open questions

- Does enabling slicer "Hole compensation" or "Elephant's foot
  compensation" change the minimum reliable hole diameter on this
  hardware? (Untested.)
- Is the +0.43 mm over-extrusion a 3D-print-orientation effect (top
  vs. bottom of part)? Re-orienting the receptacle bore along Z
  might behave differently from a horizontal-axis hole. Worth a
  follow-up coupon if vertical fit grows unreliable.
