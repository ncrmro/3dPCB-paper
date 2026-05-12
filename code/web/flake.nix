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
            # Astro 6 requires Node >= 22.12. Bun is the primary runtime
            # but `astro check` and a few transitive scripts shell out to
            # node, so keep a supported one on PATH.
            pkgs.nodejs_22
            pkgs.git
          ];

          shellHook = ''
            echo "3dPCB-paper web dev shell ready"
          '';
        };
      }
    );
}
