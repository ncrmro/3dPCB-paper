{
  description = "Bambu LAN bridge — MQTT + camera over a Unix domain socket.";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      forSystems = nixpkgs.lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
        "x86_64-darwin"
      ];
    in {
      devShells = forSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          py = pkgs.python3.withPackages (p: with p; [
            paho-mqtt
            aiohttp
          ]);
        in {
          default = pkgs.mkShell {
            name = "3dpcb-paper-bambu";
            # bambu-studio CLI: slice-on-demand for the /print endpoint.
            # Profile resolution relies on ~/.config/BambuStudio being
            # initialized once by the GUI.
            # ffmpeg: pulls the printer's RTSPS H.264 stream on :322 and
            # transcodes to MJPEG for the /camera/* fan-out.
            packages = [ py pkgs.bambu-studio pkgs.ffmpeg ];
          };
        });
    };
}
