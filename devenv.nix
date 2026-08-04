{ pkgs, lib, config, inputs, ... }:

{
  # https://devenv.sh/basics/
  env.GREET = "devenv";

  # Point tools that honor VIRTUAL_ENV (pip, pytest) at the uv-managed devenv
  # venv. devenv's uv integration pins the venv location via
  # UV_PROJECT_ENVIRONMENT, which those tools do not honor.
  env.VIRTUAL_ENV = "${config.env.DEVENV_STATE}/venv";

  # https://devenv.sh/packages/
  packages = [ 
    pkgs.git 
    pkgs.uv
    ];

  # https://devenv.sh/languages/
  # languages.rust.enable = true;
  languages = {
      python = {
          enable = true;
          version = "3.13";
          # Delegate venv management entirely to uv: uv syncs its venv (located
          # at $UV_PROJECT_ENVIRONMENT under .devenv/state) on shell entry with
          # the dev extras. devenv's own plain venv (venv.enable) would create a
          # second, dependency-free venv and shadow it via VIRTUAL_ENV.
          uv = {
              enable = true;
              sync = {
                  enable = true;
                  extras = [ "dev" ];
                };
            };
        };
    };

  # https://devenv.sh/processes/
  # processes.cargo-watch.exec = "cargo-watch";

  # https://devenv.sh/services/
  # services.postgres.enable = true;

  # https://devenv.sh/scripts/
  scripts.hello.exec = ''
    echo hello from $GREET
  '';

  enterShell = ''
    hello
    git --version
  '';

  # https://devenv.sh/tasks/
  # tasks = {
  #   "myproj:setup".exec = "mytool build";
  #   "devenv:enterShell".after = [ "myproj:setup" ];
  # };

  # https://devenv.sh/tests/
  enterTest = ''
    echo "Running tests"
    git --version | grep --color=auto "${pkgs.git.version}"
  '';

  # https://devenv.sh/pre-commit-hooks/
  # pre-commit.hooks.shellcheck.enable = true;

  # See full reference at https://devenv.sh/reference/options/
}
