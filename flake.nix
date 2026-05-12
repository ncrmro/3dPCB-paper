{
  description = "3dPCB-paper — top-level orchestration shell (process-compose, watchers)";

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
          name = "3dpcb-paper-orchestration";

          packages = [
            pkgs.process-compose
            pkgs.watchexec
            pkgs.git
          ];

          shellHook = ''
            echo "3dPCB-paper orchestration shell."
            echo "  process-compose up   — start the dev gallery (web + cad watcher + kicad watcher)"
            echo "  process-compose down — stop"
          '';
        };
      }
    );
}
