{
  description = "Application packaged using poetry2nix";

  inputs = {
    flake-utils.url = "github:numtide/flake-utils";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable-small";
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, poetry2nix }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        # see https://github.com/nix-community/poetry2nix/tree/master#api for more functions and examples.
        inherit (poetry2nix.lib.mkPoetry2Nix { inherit pkgs; }) mkPoetryApplication defaultPoetryOverrides;
        beancount-ing = mkPoetryApplication { 
          projectDir = self; 
          preferWheels = true;
          overrides = defaultPoetryOverrides.extend
            (final: prev: {
              beancount-auto-import = prev.beancount-auto-import.overridePythonAttrs
              (
                old: {
                  buildInputs = (old.buildInputs or [ ]) ++ [ prev.poetry ];
                }
              );
              }
            );
        };

        pkgs = import nixpkgs {
          inherit system;
          overlays = [
            poetry2nix.overlays.default
            (final: _: {
              myapp = final.callPackage beancount-ing { };
            })
          ];
        };
      in
      {
        packages.default = beancount-ing;
        apps.${system}.default = {
          type = "app";
          program = "${beancount-ing}/bin/beancount-ing-ec"; 
        };
        # Shell for app dependencies.
        #
        #     nix develop
        #
        # Use this shell for developing your app.
        devShells.default = pkgs.mkShell {
          inputsFrom = [ beancount-ing ];
        };

        # Shell for poetry.
        #
        #     nix develop .#poetry
        #
        # Use this shell for changes to pyproject.toml and poetry.lock.
        devShells.poetry = pkgs.mkShell {
          packages = [ pkgs.poetry ];
        };
      });
}
