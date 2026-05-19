{
  description = "Plant Caravan CAD - Parametric ESP32 sensor enclosures";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    # Pinned to a known-good commit so `nix develop` doesn't hit
    # GitHub's anonymous API rate limit fetching HEAD on cold caches.
    # Bump as needed; verify with `cd code/cad && nix develop -c ./bin/render`.
    cadeng.url = "github:ncrmro/cadeng/5d0d3f9251bc3708815a2c559fd5a0b1581b95da";
  };

  outputs = { self, nixpkgs, flake-utils, cadeng }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        devShells.default = pkgs.mkShell {
          name = "plant-caravan-cad";

          packages = [
            # CADeng server (compiled binary, provides `cadeng` CLI)
            cadeng.packages.${system}.default

            # Python 3.13
            pkgs.python313

            # Package manager
            pkgs.uv

            # CAD tools (wrapped openscad with EGL headless support)
            cadeng.packages.${system}.openscad

            # STL -> GLB conversion for the Astro <model-viewer> gallery.
            pkgs.assimp

            # STEP tessellation for third-party CAD vitamins under
            # data/models/. We use FreeCADCmd (headless) to read STEP
            # and emit STL, then trimesh (already a Python dep) to
            # write GLB. assimp's STEP importer is IFC-only and won't
            # read mechanical AP203/AP214 STEPs.
            pkgs.freecad

            # Build dependencies for Python packages
            pkgs.stdenv.cc.cc.lib
            pkgs.zlib
            pkgs.libGL
            pkgs.libGLU
            pkgs.libx11
            pkgs.libxext
            pkgs.libxrender

            # Development tools
            pkgs.git
          ];

          shellHook = ''
            # Set up library paths for Python native extensions
            export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath [
              pkgs.stdenv.cc.cc.lib
              pkgs.zlib
              pkgs.libGL
              pkgs.libGLU
              pkgs.libx11
              pkgs.libxext
              pkgs.libxrender
            ]}:$LD_LIBRARY_PATH"

            # Create virtual environment if it doesn't exist
            if [ ! -d .venv ]; then
              echo "Creating virtual environment..."
              uv venv
            fi

            # Sync dependencies
            echo "Syncing dependencies..."
            uv sync --quiet

            # Activate virtual environment
            source .venv/bin/activate

            echo "Plant Caravan CAD dev shell ready!"
            echo "Run './bin/test' to run tests"
            echo "Run './bin/render' to generate SCAD/STL files"
            echo "Run 'cadeng' to start the gallery server"
          '';
        };
      }
    );
}
