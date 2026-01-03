{
  description = "Whisper on MLX - dev shell (Mac)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs = { self, nixpkgs, ... }:
  let
    pkgs = import nixpkgs {
      system = "aarch64-darwin";
      # For Intel Macs use x86_64-darwin, but MLX is for Apple Silicon.
    };
  in {
    devShells.aarch64-darwin.default = pkgs.mkShell {
      packages = with pkgs; [
        # Python + tooling
        python312
        python312Packages.virtualenv
        # Media backend for Whisper
        ffmpeg
        # Node.js for pyright
        nodejs_22
        # Helpful
        git
        pkg-config
      ];
      # Keep Python tidy/isolated
      shellHook = ''
        export PYTHONNOUSERSITE=1
        echo "🐍 Use:  python -m venv .venv && source .venv/bin/activate"
      '';
    };
  };
}
