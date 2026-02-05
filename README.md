# Boomtube (MVP)

Boomtube is a small Python library + CLI that reads a `boomtube.yaml` in a project root and ensures a set of symlinks exist, optionally performing a one-time non-destructive migration if the link path already exists as a real file/directory.

## CLI

- `boomtube apply` — apply the config.

## Config

See `Boomtube_IMPLEMENTATION_GUIDE.md` / `Boomtube_SPEC.md` from the project docs.
