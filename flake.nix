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
        # Node.js + pnpm for frontend
        nodejs_22
        nodePackages.pnpm
        # Helpful
        git
        pkg-config
      ];
      # Note: On macOS, browser E2E tests use system Chrome/chromedriver
      # On Linux, add chromium and chromedriver to packages above
      # Keep Python tidy/isolated
      shellHook = ''
        export PYTHONNOUSERSITE=1
        echo "🐍 Use:  python -m venv .venv && source .venv/bin/activate"
      '';
    };
  };
}
