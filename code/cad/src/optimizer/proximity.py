"""Module-centre distance + stack-overlap helpers."""

from __future__ import annotations

from .plan_parser import ParsedPlan, Pocket


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def module_centre(plan: ParsedPlan, module_key: str) -> tuple[float, float]:
    """Best available centre for `module_key`.

    Order of preference:
    1. Pocket centre from section 4
    2. Mid-pin of the module's column (pin-1 + (n-1)/2 · pitch)
    """
    for p in plan.pockets:
        if p.module == module_key:
            return p.centre
    for m in plan.modules:
        if _module_key_for(m) == module_key:
            mid = m.pin_xy((m.pin_count + 1) // 2)
            return mid
    raise KeyError(f"no anchor for module {module_key!r}")


def _module_key_for(module) -> str:
    """Mirror of plan_parser._module_key_for, applied to a ModuleAnchor."""
    label = module.label
    upper = label.upper()
    for needle in ("OLED", "SSD1306", "ESP32-C3", "SUPERMINI", "ESP32",
                   "SCD41", "BH1750"):
        if needle in upper:
            if needle in ("OLED", "SSD1306"):
                return "OLED"
            if needle in ("ESP32-C3", "SUPERMINI", "ESP32"):
                return "ESP32"
            return needle
    return label.split()[0].upper()


def centre_to_centre_mm(plan: ParsedPlan, a: str, b: str) -> float:
    return _dist(module_centre(plan, a), module_centre(plan, b))


def stacks_overlap(plan: ParsedPlan, a: str, b: str) -> bool:
    """xy projections overlap if either pocket bounding rect overlaps
    or a cantilever bounds box overlaps the other module's centre."""
    rects = []
    for mod in (a, b):
        rect = _pocket_rect_or_cantilever(plan, mod)
        if rect is None:
            return False
        rects.append(rect)
    return _rects_overlap(rects[0], rects[1])


def _pocket_rect_or_cantilever(plan: ParsedPlan, module: str):
    for p in plan.pockets:
        if p.module != module:
            continue
        if p.cantilever_xy_bounds is not None:
            return p.cantilever_xy_bounds
        if p.width_mm and p.height_mm:
            cx, cy = p.centre
            return (cx - p.width_mm / 2, cx + p.width_mm / 2,
                    cy - p.height_mm / 2, cy + p.height_mm / 2)
    return None


def _rects_overlap(r1, r2) -> bool:
    return not (r1[1] < r2[0] or r2[1] < r1[0] or r1[3] < r2[2] or r2[3] < r1[2])
