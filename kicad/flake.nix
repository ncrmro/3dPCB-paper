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
            pkgs.git
          ];

          shellHook = ''
            echo "3dPCB-paper KiCad dev shell ready."
            echo "  kicad      — open the GUI"
            echo "  kicad-cli  — headless tooling (Gerber export, ERC, DRC)"
          '';
        };
      }
    );
}
