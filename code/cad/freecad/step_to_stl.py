"""Tessellate a STEP file to STL inside FreeCAD's embedded Python.

Invoked as `FreeCADCmd path/to/this/file STEP_IN=... STL_OUT=... DEFLECTION=...`
from the bash wrapper. Lives as a real file (not a `-c` string) because
FreeCADCmd's `-c` flag mishandles multi-line scripts in 1.1.1.

Inputs come through environment variables:
    STEP_IN     absolute path to the source .step / .stp
    STL_OUT     absolute path to write the STL
    DEFLECTION  OCC linear deflection in mm; smaller = finer mesh
"""

import os

import FreeCAD
import Import
import Mesh

step_in = os.environ["STEP_IN"]
stl_out = os.environ["STL_OUT"]
deflection = float(os.environ["DEFLECTION"])

doc = FreeCAD.newDocument("conv")
Import.insert(step_in, doc.Name)

solids = [o for o in doc.Objects if hasattr(o, "Shape") and o.Shape.Volume > 0]
if not solids:
    raise SystemExit(f"step_to_stl: no solids in {step_in}")

mesh = Mesh.Mesh()
for o in solids:
    mesh.addFacets(o.Shape.tessellate(deflection))
mesh.write(stl_out)
