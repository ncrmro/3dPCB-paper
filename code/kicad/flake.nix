{
  description = "3dPCB-paper KiCad — EDA tooling for the canonical electrical design";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        devShells.default = pkgs.mkShell {
          name = "3dpcb-paper-kicad";

          packages = [
            pkgs.kicad
            pkgs.kicad.libraries.packages3d
            pkgs.git
          ];

          shellHook = ''
            # CRITICAL: kicad-cli resolves packaged .wrl / .step component
            # meshes via KICAD9_3DMODEL_DIR. Without this, board geometry
            # still renders but every footprint with a 3D model logs a
            # missing-mesh warning and the GLB export omits parts.
            # WHY libraries.packages3d: the bundled pkgs.kicad ships no
            # 3dmodels by default; the separate derivation provides the
            # full Connector_PinSocket / PinHeader meshes referenced from
            # spike.kicad_pcb (CC-BY-SA 4.0 + KiCad library exception).
            export KICAD9_3DMODEL_DIR="${pkgs.kicad.libraries.packages3d}/share/kicad/3dmodels"

            echo "3dPCB-paper KiCad dev shell ready."
            echo "  kicad             — open the GUI"
            echo "  kicad-cli         — headless tooling (Gerber export, ERC, DRC)"
            echo "  bin/render-board  — three-view PNG (iso/top/bottom) to build/"
            echo "  bin/render-glb    — export .kicad_pcb to GLB into build/"
          '';
        };
      }
    );
}
