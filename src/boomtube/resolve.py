from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path


class VarResolutionError(RuntimeError):
    pass


def render_template(template: str, ctx: Mapping[str, str]) -> str:
    """Render a string template using `{var}` placeholders.

    Normalizes the full set of template failure modes (missing keys, stray
    braces, positional fields) into a typed `VarResolutionError`.
    """
    try:
        # `format_map` accepts any Mapping. Avoid converting to dict (which would
        # eagerly iterate keys) so variables can resolve lazily.
        return template.format_map(ctx)
    except KeyError as e:
        raise VarResolutionError(f"Missing variable: {e.args[0]}") from e
    except (ValueError, IndexError) as e:
        raise VarResolutionError(f"Invalid template {template!r}: {e}") from e


def render(template: str, ctx: Mapping[str, str]) -> str:
    """Render a string template using `{var}` placeholders.

    Raises VarResolutionError on missing keys.
    """
    return render_template(template, ctx)


def build_context(project_root: Path, user_vars: dict[str, str] | None) -> dict[str, str]:
    builtins = {
        "project_root": str(project_root),
        "project_name": project_root.name,
    }
    user_vars = user_vars or {}
    resolved_user = resolve_vars(user_vars, builtins)
    # Builtins win: even if a user var shares a name, `{project_root}` must
    # always resolve to the real project root (I4). Config validation rejects
    # such vars (F16); this merge order is defense in depth.
    return {**resolved_user, **builtins}


def resolve_vars(vars_dict: dict[str, str], builtins: dict[str, str], *, recursion_limit: int = 50) -> dict[str, str]:
    """Resolve user vars allowing references to builtins and other vars.

    Uses DFS with cycle detection.
    """

    resolved: dict[str, str] = {}
    visiting: set[str] = set()

    def _resolve_key(key: str, depth: int) -> str:
        if key in resolved:
            return resolved[key]
        if key in visiting:
            raise VarResolutionError(f"Cycle detected while resolving var '{key}'")
        if depth > recursion_limit:
            raise VarResolutionError("Variable resolution recursion limit exceeded")
        if key not in vars_dict:
            raise VarResolutionError(f"Unknown variable '{key}'")

        visiting.add(key)

        # Render using a context that can recursively fetch other vars.
        class _Ctx(Mapping[str, str]):
            def __getitem__(self, k: str) -> str:
                if k in builtins:
                    return builtins[k]
                if k in resolved:
                    return resolved[k]
                if k in vars_dict:
                    return _resolve_key(k, depth + 1)
                raise KeyError(k)

            def __iter__(self):
                yield from set(builtins) | set(vars_dict) | set(resolved)

            def __len__(self):
                return len(set(builtins) | set(vars_dict) | set(resolved))

        try:
            out = render_template(vars_dict[key], _Ctx())
        except VarResolutionError as e:
            raise VarResolutionError(f"{e} (while resolving '{key}')") from e
        finally:
            visiting.remove(key)

        resolved[key] = out
        return out

    for k in vars_dict.keys():
        _resolve_key(k, 0)

    return resolved
