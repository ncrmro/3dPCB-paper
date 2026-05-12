{
  description = "3dPCB-paper web — Astro gallery for substrate/PCB embodiment pairs";

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
          name = "3dpcb-paper-web";

          packages = [
            pkgs.bun
            pkgs.nodejs_20
            pkgs.git
          ];

          shellHook = ''
            echo "3dPCB-paper web dev shell ready"
          '';
        };
      }
    );
}
