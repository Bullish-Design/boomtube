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

  # devman — the automation plane (CONCEPT.md §5). `base` alone: this repository
  # ships no scheduled work and writes none of its own files.
  devman = {
    enable = true;
    project = "boomtube";
    groups = [ "base" ];
  };

  # https://devenv.sh/tasks/
  #
  # The two task names the `base` group calls (groups/base/README.md). devenv
  # owns each implementation; Dagu owns the composition (§6).
  #
  # `pytest` lives in `[project.optional-dependencies].dev`, which devenv's venv
  # does not install — hence `uv run --extra dev` (STAGE_7_LOG.md, wave 2b).
  # `ruff check src` matches the repo's own `src = ["src"]` scope; the full
  # tree carries 241 findings in `.scratch/` repros, which are not source.
  tasks = {
    "boomtube:lint".exec = "uv run --extra dev ruff check src";
    "boomtube:test".exec = "uv run --extra dev pytest";

    "base:check".after = [ "boomtube:lint" ];
    "base:test".after = [ "boomtube:test" ];
  };

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
