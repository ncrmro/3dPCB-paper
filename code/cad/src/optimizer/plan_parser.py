"""Parse `substrate_plan.md` → `ParsedPlan` dataclass.

The parser is special-cased to the layout enforced by the DeepSchema
at `.deepwork/schemas/printable_pcb_substrate_plan/deepschema.yml`:
nine numbered sections, markdown tables for modules / nets / through-
holes, prose with explicit "centre (x, y)" entries in section 4, and
fenced ```yaml``` blocks in section 6 carrying segments + vias.

Things the parser is deliberately lenient about:
  - section 5 may be a stub ("see v1 plan"); pin coords get recomputed
    from the module table's pin-1 + pitch + pad-direction in that case
  - module table cells may embed a column ref like "(J1A col)" or
    "J2.1 (5, -17)" — both forms are recognized
  - the net list may include pseudo-entries (`J1A_unused_{...}`) — they
    are skipped (singletons; not real merge candidates)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

import yaml


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModuleAnchor:
    """One module entry from Section 2 — represents a pin column."""

    label: str               # raw row title, e.g. "ESP32-C3 SuperMini (J1A col)"
    column_ref: str          # extracted column ref: "J1A", "J1B", "J2", "J3", "J4"
    vitamin: str
    pin1_xy: tuple[float, float]
    pad_direction: str       # "+X", "-X", "+Y", "-Y"
    pin_count: int
    pitch: float

    def pin_xy(self, pin_number: int) -> tuple[float, float]:
        """Compute the (x, y) of pin N (1-indexed) from pin-1 + pitch."""
        delta = (pin_number - 1) * self.pitch
        x, y = self.pin1_xy
        if self.pad_direction == "+X":
            return (x + delta, y)
        if self.pad_direction == "-X":
            return (x - delta, y)
        if self.pad_direction == "+Y":
            return (x, y + delta)
        if self.pad_direction == "-Y":
            return (x, y - delta)
        raise ValueError(f"unknown pad_direction {self.pad_direction!r}")


@dataclass(frozen=True)
class Pocket:
    module: str                            # module key (e.g. "ESP32", "SCD41")
    centre: tuple[float, float]
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None
    depth_mm: Optional[float] = None
    # OLED-style cantilever: PCB body extends past the substrate
    cantilever_xy_bounds: Optional[tuple[float, float, float, float]] = None
    # (x_min, x_max, y_min, y_max)


@dataclass(frozen=True)
class ThroughHole:
    xy: tuple[float, float]
    pin_ref: str        # "J2.1" etc, or empty when uninferred
    net: str            # net name as written, lowercased; "" if unknown
    diameter: float


@dataclass(frozen=True)
class WireSegment:
    layer: int
    start: tuple[float, float]
    end: tuple[float, float]

    def length_mm(self) -> float:
        return _dist(self.start, self.end)


@dataclass(frozen=True)
class Via:
    position: tuple[float, float]
    diameter: float


@dataclass(frozen=True)
class NetRouting:
    name: str                              # lowercased net name: "vcc", "gnd"
    segments: tuple[WireSegment, ...]
    vias: tuple[Via, ...]

    def total_wire_mm(self) -> float:
        return sum(s.length_mm() for s in self.segments)


@dataclass(frozen=True)
class NetEndpoints:
    """One row of section 3's net list table."""

    name: str                              # raw net name as written
    pin_refs: tuple[str, ...]              # e.g. ("J1A.3", "J2.1", "J3.1")


@dataclass(frozen=True)
class ParsedPlan:
    source_path: str
    board_name: str
    modules: tuple[ModuleAnchor, ...]
    nets: tuple[NetEndpoints, ...]
    pockets: tuple[Pocket, ...]
    through_holes: tuple[ThroughHole, ...]
    net_routings: tuple[NetRouting, ...]
    warnings: tuple[tuple[str, str], ...] = ()

    def module_by_column(self, column_ref: str) -> Optional[ModuleAnchor]:
        for m in self.modules:
            if m.column_ref == column_ref:
                return m
        return None

    def pin_xy(self, pin_ref: str) -> Optional[tuple[float, float]]:
        """Resolve a pin reference like 'J2.1' → (x, y)."""
        m = re.match(r"^([A-Za-z0-9]+)\.(\d+)$", pin_ref.strip())
        if not m:
            return None
        col, num = m.group(1), int(m.group(2))
        anchor = self.module_by_column(col)
        if anchor is None:
            return None
        return anchor.pin_xy(num)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


# (x, y) — accepts ints, floats, leading +/- and spaces.
_COORD_RE = re.compile(r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)")

# Module key extraction: "ESP32-C3 SuperMini (J1A col)" → "ESP32"-ish,
# "SCD41 breakout" → "SCD41", "Hosyond SSD1306 OLED (J4)" → "OLED"
_MODULE_KEY_OVERRIDES = {
    "ESP32-C3": "ESP32",
    "SuperMini": "ESP32",
    "SCD41": "SCD41",
    "BH1750": "BH1750",
    "OLED": "OLED",
    "SSD1306": "OLED",
}


def _module_key_for(label: str) -> str:
    upper = label.upper()
    for needle, key in _MODULE_KEY_OVERRIDES.items():
        if needle.upper() in upper:
            return key
    # Fallback: first word
    return label.split()[0].upper()


# ---------------------------------------------------------------------------
# Section splitting
# ---------------------------------------------------------------------------


_SECTION_HEADER_RE = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$", re.MULTILINE)


def _split_sections(text: str) -> dict[int, str]:
    """Return {section_number: body_text} keyed by the leading number."""
    indices: list[tuple[int, int, str]] = []
    for m in _SECTION_HEADER_RE.finditer(text):
        indices.append((int(m.group(1)), m.start(), m.group(2)))
    indices.append((-1, len(text), ""))  # sentinel
    sections: dict[int, str] = {}
    for i in range(len(indices) - 1):
        num, start, _ = indices[i]
        end = indices[i + 1][1]
        # Skip the header line itself
        body_start = text.find("\n", start)
        if body_start == -1:
            body_start = start
        sections[num] = text[body_start + 1 : end]
    return sections


# ---------------------------------------------------------------------------
# Section 1 — board identity
# ---------------------------------------------------------------------------


_BOARD_NAME_RE = re.compile(r"\*\*board_name\*\*\s*:\s*`?([\w-]+)`?")


def _parse_board_name(section1: str) -> str:
    m = _BOARD_NAME_RE.search(section1)
    return m.group(1) if m else "unknown"


# ---------------------------------------------------------------------------
# Section 2 — modules
# ---------------------------------------------------------------------------


def _parse_modules(section2: str, warnings: list) -> list[ModuleAnchor]:
    out: list[ModuleAnchor] = []
    for row in _iter_table_rows(section2):
        if len(row) < 6:
            continue
        label, vitamin, pin1_cell, rotation, pins, pitch = row[:6]
        column_ref = _extract_column_ref(label, pin1_cell)
        if column_ref is None:
            warnings.append((
                "parser_warning",
                f"could not extract column ref from module row '{label}'",
            ))
            continue
        coord_match = _COORD_RE.search(pin1_cell)
        if not coord_match:
            warnings.append((
                "parser_warning",
                f"could not extract pin-1 coord from '{pin1_cell}'",
            ))
            continue
        pin1_xy = (float(coord_match.group(1)), float(coord_match.group(2)))
        pad_direction = _normalize_pad_direction(rotation)
        try:
            pin_count = int(pins.strip())
            pitch_f = float(pitch.strip())
        except ValueError:
            warnings.append((
                "parser_warning",
                f"could not parse pin_count/pitch from '{pins}'/'{pitch}' in row '{label}'",
            ))
            continue
        out.append(ModuleAnchor(
            label=label.strip(),
            column_ref=column_ref,
            vitamin=vitamin.strip().strip("`"),
            pin1_xy=pin1_xy,
            pad_direction=pad_direction,
            pin_count=pin_count,
            pitch=pitch_f,
        ))
    return out


_COLUMN_REF_RE = re.compile(r"\b(J\d+[A-Z]?)\b")


def _extract_column_ref(label: str, pin1_cell: str) -> Optional[str]:
    # "(J1A col)" / "(J1B col)" forms
    m = _COLUMN_REF_RE.search(label)
    if m:
        return m.group(1)
    # "J2.1 (5, -17)" form
    m = re.search(r"\b(J\d+[A-Z]?)\.\d+\b", pin1_cell)
    if m:
        return m.group(1)
    # "(J4)" form on the label
    m = re.search(r"\((J\d+[A-Z]?)\)", label)
    if m:
        return m.group(1)
    return None


def _normalize_pad_direction(rotation_cell: str) -> str:
    s = rotation_cell.strip().lower()
    if "+y" in s:
        return "+Y"
    if "-y" in s:
        return "-Y"
    if "+x" in s:
        return "+X"
    if "-x" in s:
        return "-X"
    return "+Y"


# ---------------------------------------------------------------------------
# Section 3 — net list
# ---------------------------------------------------------------------------


_PIN_REF_RE = re.compile(r"\bJ\d+[A-Z]?\.\d+\b")


def _parse_nets(section3: str, warnings: list) -> list[NetEndpoints]:
    out: list[NetEndpoints] = []
    for row in _iter_table_rows(section3):
        if len(row) < 2:
            continue
        name_cell, endpoints_cell = row[0], row[1]
        name = name_cell.strip().strip("`")
        if "{" in name or "..." in name:  # pseudo-entries like J1A_unused_{1,4..9}
            continue
        refs = tuple(_PIN_REF_RE.findall(endpoints_cell))
        if not refs:
            continue
        out.append(NetEndpoints(name=name, pin_refs=refs))
    return out


# ---------------------------------------------------------------------------
# Section 4 — pockets + cantilevers
# ---------------------------------------------------------------------------


_POCKET_LINE_RE = re.compile(
    r"^-\s*([A-Za-z0-9_]+).*?centre\s*\(\s*(-?\d+(?:\.\d+)?)\s*,\s*"
    r"(-?\d+(?:\.\d+)?|[a-z_]+)\s*\)",
    re.MULTILINE,
)


def _parse_pockets(section4: str, warnings: list) -> list[Pocket]:
    out: list[Pocket] = []
    for m in _POCKET_LINE_RE.finditer(section4):
        module = m.group(1).upper()
        try:
            cx = float(m.group(2))
            cy = float(m.group(3))
        except ValueError:
            # cy is a symbolic placeholder ("scd_cy") in the v1 plan —
            # treat as missing and skip; not critical for proximity.
            warnings.append((
                "parser_warning",
                f"pocket centre for {module} has symbolic y '{m.group(3)}' — skipped",
            ))
            continue
        out.append(Pocket(module=module, centre=(cx, cy)))

    # Cantilever extraction: look for "occupies x ∈ [..., ...], y ∈ [..., ...]"
    cant_re = re.compile(
        r"occupies\s*x\s*∈\s*\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]"
        r"\s*,\s*y\s*∈\s*\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]"
    )
    # Heuristic: cantilever belongs to the most-recent OLED-ish bullet.
    if "cantilever" in section4.lower() or "OLED" in section4:
        m = cant_re.search(section4)
        if m:
            bounds = (float(m.group(1)), float(m.group(2)),
                      float(m.group(3)), float(m.group(4)))
            # Replace OLED pocket (if any) with a cantilever-bearing one,
            # or add a synthetic OLED entry if no centre was listed.
            new_out: list[Pocket] = []
            saw_oled = False
            for p in out:
                if p.module == "OLED":
                    new_out.append(Pocket(
                        module=p.module,
                        centre=p.centre,
                        width_mm=p.width_mm,
                        height_mm=p.height_mm,
                        depth_mm=p.depth_mm,
                        cantilever_xy_bounds=bounds,
                    ))
                    saw_oled = True
                else:
                    new_out.append(p)
            if not saw_oled:
                # Derive a centre from the cantilever bounds
                cx = (bounds[0] + bounds[1]) / 2
                cy = (bounds[2] + bounds[3]) / 2
                new_out.append(Pocket(
                    module="OLED",
                    centre=(cx, cy),
                    cantilever_xy_bounds=bounds,
                ))
                warnings.append((
                    "parser_warning",
                    "OLED pocket centre inferred from cantilever bounds; "
                    "section 4 prose did not list an explicit centre",
                ))
            out = new_out
    return out


# ---------------------------------------------------------------------------
# Section 5 — through-hole table (optional)
# ---------------------------------------------------------------------------


def _parse_through_holes(section5: str, warnings: list) -> list[ThroughHole]:
    out: list[ThroughHole] = []
    for row in _iter_table_rows(section5):
        if len(row) < 4:
            continue
        coord_cell, pin_cell, net_cell, diam_cell = row[:4]
        coord_match = _COORD_RE.search(coord_cell)
        if not coord_match:
            continue
        try:
            diameter = float(diam_cell.strip())
        except ValueError:
            continue
        out.append(ThroughHole(
            xy=(float(coord_match.group(1)), float(coord_match.group(2))),
            pin_ref=pin_cell.strip(),
            net=net_cell.strip().lower(),
            diameter=diameter,
        ))
    if not out and "See" in section5:
        warnings.append((
            "parser_warning",
            "section 5 is a stub — through-hole positions will be derived "
            "from module pin-1 + pitch where needed",
        ))
    return out


# ---------------------------------------------------------------------------
# Section 6 — per-net routing (inline YAML blocks)
# ---------------------------------------------------------------------------


_YAML_BLOCK_RE = re.compile(r"```yaml\s*\n(.*?)\n```", re.DOTALL)


def _parse_net_routings(section6: str, warnings: list) -> list[NetRouting]:
    out: list[NetRouting] = []
    for m in _YAML_BLOCK_RE.finditer(section6):
        body = m.group(1)
        try:
            data = yaml.safe_load(body)
        except yaml.YAMLError as e:
            warnings.append(("parser_warning", f"yaml block parse error: {e}"))
            continue
        if not isinstance(data, dict) or "net" not in data:
            continue
        name = str(data.get("net", "")).lower()
        segments: list[WireSegment] = []
        for seg in data.get("segments") or []:
            segments.append(WireSegment(
                layer=int(seg["layer"]),
                start=(float(seg["start"][0]), float(seg["start"][1])),
                end=(float(seg["end"][0]), float(seg["end"][1])),
            ))
        vias: list[Via] = []
        for v in data.get("vias") or []:
            vias.append(Via(
                position=(float(v["position"][0]), float(v["position"][1])),
                diameter=float(v.get("diameter", 1.5)),
            ))
        out.append(NetRouting(name=name, segments=tuple(segments), vias=tuple(vias)))
    return out


# ---------------------------------------------------------------------------
# Markdown table iterator
# ---------------------------------------------------------------------------


def _iter_table_rows(section: str):
    """Yield each data row of every markdown table in `section` as a
    list of cell strings (header + separator rows stripped)."""
    for table in _find_tables(section):
        rows = [r for r in table.split("\n") if r.strip().startswith("|")]
        if len(rows) < 2:
            continue
        # Drop header + separator (the line of |---|---|)
        for row in rows[2:]:
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            yield cells


def _find_tables(section: str) -> list[str]:
    """Return contiguous blocks of lines starting with `|`."""
    tables: list[str] = []
    current: list[str] = []
    for line in section.split("\n"):
        if line.strip().startswith("|"):
            current.append(line)
        else:
            if current:
                tables.append("\n".join(current))
                current = []
    if current:
        tables.append("\n".join(current))
    return tables


# ---------------------------------------------------------------------------
# Top-level entrypoint
# ---------------------------------------------------------------------------


def parse_plan(path: str) -> ParsedPlan:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    return _parse_plan_text(text, source_path=path)


def _parse_plan_text(text: str, *, source_path: str = "<inline>") -> ParsedPlan:
    sections = _split_sections(text)
    warnings: list[tuple[str, str]] = []

    board_name = _parse_board_name(sections.get(1, ""))
    modules = _parse_modules(sections.get(2, ""), warnings)
    nets = _parse_nets(sections.get(3, ""), warnings)
    pockets = _parse_pockets(sections.get(4, ""), warnings)
    through_holes = _parse_through_holes(sections.get(5, ""), warnings)
    net_routings = _parse_net_routings(sections.get(6, ""), warnings)

    # Section 5 may be a stub ("see v1 plan") or list only the new
    # holes a refresh added. Either way, fill in any module pin not
    # already present so the collision check has the full pin grid.
    # Explicit section-5 entries win over synthesized ones (they carry
    # the right diameter, e.g. 1.25 mm receptacles vs 1.0 mm pins).
    if modules:
        existing = {h.pin_ref for h in through_holes}
        net_for_pin = _build_pin_to_net_map(nets)
        synthesized: list[ThroughHole] = list(through_holes)
        for m in modules:
            for i in range(1, m.pin_count + 1):
                ref = f"{m.column_ref}.{i}"
                if ref in existing:
                    continue
                synthesized.append(ThroughHole(
                    xy=m.pin_xy(i),
                    pin_ref=ref,
                    net=net_for_pin.get(ref, ""),
                    diameter=1.0,
                ))
        through_holes = synthesized

    return ParsedPlan(
        source_path=source_path,
        board_name=board_name,
        modules=tuple(modules),
        nets=tuple(nets),
        pockets=tuple(pockets),
        through_holes=tuple(through_holes),
        net_routings=tuple(net_routings),
        warnings=tuple(warnings),
    )


def _build_pin_to_net_map(nets) -> dict[str, str]:
    out: dict[str, str] = {}
    for net in nets:
        for ref in net.pin_refs:
            out[ref] = net.name.lower().strip("`+")
    return out
