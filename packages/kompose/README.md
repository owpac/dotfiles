# Kompose

CLI for managing Docker Compose services on the homelab.

## Installation

Installed via [pipx](https://pipx.pypa.io) in editable mode from this repo. The
chezmoi script at `home/.chezmoiscripts/run_onchange_after_install-kompose.sh.tmpl`
handles this automatically on `chezmoi apply` whenever `pyproject.toml` changes.

Manual install:

```bash
pipx install --editable ~/.dotfiles/packages/kompose --force
```

This creates an isolated venv at `~/.local/pipx/venvs/kompose/` with PyYAML
installed, and exposes `kompose` in `~/.local/bin/`. Code changes in
`~/.dotfiles/packages/kompose/src/` are picked up live (editable mode).

A future Homebrew tap is drafted at `brew/` — see `brew/README.md`.

## Usage

```bash
kompose <command> [options]
```

### Commands

The CLI follows a **noun-verb** canonical form (`service <verb>`, `env <verb>`)
with short top-level aliases for daily use. Both forms are first-class.

**Top-level (daily ergonomics)**

| Command | Description |
|---------|-------------|
| `up [service] [containers...]` | Start services (alias of `service up`) |
| `down [service] [containers...]` | Stop services (alias of `service down`) |
| `restart [service] [containers...]` | Restart services (alias of `service restart`) |
| `logs <service> [containers...]` | View service logs (alias of `service logs`) |
| `status [service]` | Show services status (alias of `service status`) |
| `check [service]` | Lint compose.yml + env drift against declarative rules |
| `fix [service]` | Auto-fix what can be fixed (today: env sync) |

**Canonical forms**

| Command | Description |
|---------|-------------|
| `service up\|down\|restart\|logs\|status [name] [containers...]` | Service lifecycle |
| `env fix [service]` | Interactive `.env` / `.env.example` sync |

### Options

| Option | Description |
|--------|-------------|
| `-h, --help` | Show help |
| `-v, --version` | Show version |
| `--no-color` | Disable colored output |
| `--host HOST` | Override host (default: nas) |

### Examples

```bash
kompose up                       # Start all services
kompose up paperless             # Start a single service
kompose up servarr               # Start a group (= all services in servarr/compose.yml)
kompose up servarr plex          # Start specific container(s) inside a group
kompose restart sonarr radarr    # Restart by service name(s)
kompose down                     # Stop all services
kompose logs paperless -n 50
kompose status                   # Rich table of all services
kompose status traefik           # Filtered table + last 30 log lines
kompose status traefik -f        # Same, follow logs continuously
kompose status traefik -n 100    # Show last 100 log lines instead
kompose status traefik --no-logs # Just the filtered table, no logs
kompose check                    # Lint everything (compose + env)
kompose check paperless          # Lint a single service
kompose fix                      # Apply auto-fixes (today: env sync)
kompose fix -f                   # Non-interactive
kompose fix --dry-run            # Preview without applying
kompose env fix paperless        # Scoped env sync for one service
kompose service status           # Canonical form of `kompose status`
kompose --host other up          # Use different host directory
```

## Execution modes

Kompose auto-detects how to invoke `docker compose`:

- **Root mode** — used when `<host>/compose.yml` exists. All services are unified
  under a single Docker Compose project via `include:` directives. Commands target
  the root file; positional args expand to docker compose service names. If an arg
  matches a directory containing a `compose.yml` (a "group"), it expands to all
  services declared in that file. Otherwise it is passed through as-is.

- **Legacy mode** — when no root compose.yml exists. Falls back to the per-service
  iteration model with optional layering of `base/<service>/compose.yml` +
  `<host>/<service>/compose.yml`. Preserved for hosts that haven't adopted the
  include model.

The mode is selected per command at runtime; no configuration needed.

## Check (lint)

```bash
kompose check            # Lint all services
kompose check servarr    # Lint specific service
```

The lint engine is fully driven by a declarative rule file. Rules are loaded
from `<host>/.kompose/` in the homelab workspace:

```
/mnt/home/thomas/workspace/homelab/<host>/.kompose/
  rules.yaml                  # single-file layout
  # OR
  globals.yaml                # multi-file layout
  rules/
    <rule>.yaml
    ...
```

Both layouts can coexist; rules are merged by `name:` (duplicate names raise
an error).

A ready-to-copy example is provided at `examples/rules.yaml` — it reproduces
the rules that were previously hardcoded.

Output:

```
Service   Structure  Traefik  Logging  Network  Compose
─────────────────────────────────────────────────────────
appA      -          -        -        -        -
appB      2          -        1        -        -
appC      -          1        -        -        -
appD      -          -        -        -        1

appB
  property-order: radarr:42 move `image` before `container_name`
  logging-driver: missing 'driver: local'

appC
  traefik-router-naming: my-router (missing -private/-public)

appD
  compose-includes-sync: not in root compose include (compose.yml)

Notices — compose-includes-sync
  ● compose.yml include path missing on disk: ghost/compose.yml
```

Columns are derived from each rule's `category:`. Counts show error /
warning issues per category. Exit code is `1` when any `error`-severity issue
is reported (including notices).

### Rule schema

```yaml
globals:               # shared values, passed to handlers via ctx.globals
  public_domain: owpac.com
  private_domain: owpac.net
  proxy_network: reverse-proxy
  public_middleware: wan@file
  private_middleware: lan@file

rules:
  - name: <unique-id>         # rule identifier (must be unique)
    category: <string>        # column in the lint table
    severity: error           # error (default) | warning
    type: <builtin-type>      # OR `handler:` (exactly one)
    handler: <module-name>    # Python handler in kompose.rules.<name>
    exclude: [<items>]        # interpreted by the type/handler
    params:                   # passed to the type/handler
      ...
```

### Built-in types (YAML-only rules)

| Type | Params | `exclude:` semantics |
|------|--------|----------------------|
| `substring_required` | `required: [str, ...]` | service names to skip |
| `substring_forbidden` | `forbidden: [str, ...]` | service names to skip |
| `property_order` | `order: [key, ...]`, `warn_on_unknown: bool` (default `true`) | container names (inside `services:`) to skip |

`property_order.warn_on_unknown`: when true (the default), each YAML key
that is NOT in `order:` is flagged with its own warning ("unknown property
`build` (not in rule's `order` list)"). Auto-fix is **not** applied to
unknowns — only known props are reordered in place, leaving unknowns where
the user placed them. Set to `false` to silence the warnings if you want
the order list to be advisory rather than exhaustive.

Examples:

```yaml
- name: no-latest-tag
  category: security
  type: substring_forbidden
  severity: warning
  params:
    forbidden: [":latest"]

- name: logging-driver
  category: logging
  type: substring_required
  params:
    required: ["logging:", "driver: local"]

- name: property-order
  category: structure
  type: property_order
  params:
    order: [container_name, depends_on, env_file, environment, ...]
```

### Python handlers (for complex rules)

Built-in handlers live in `src/kompose/rules/`:

| Handler | Purpose | `exclude:` semantics | Auto-fix |
|---------|---------|----------------------|----------|
| `traefik_router_naming` | Public routers must use `-private`/`-public` suffix | router names | — |
| `traefik_middleware_correlation` | Public→wan@file, private→lan@file | router names | — |
| `reverse_proxy_network` | Service must use proxy network or `network_mode` | service names | — |
| `compose_includes_sync` | Service dirs ↔ `<host>/compose.yml` `include:` stay in sync | service / dir names | ✓ (direction A: adds missing dir to includes) |
| `env_check` | `.env` ↔ `.env.example` parity (vars + structure). Shares its check logic with `kompose env fix`. | service names | via `kompose env fix` |

Built-in YAML types with auto-fix: `property_order` (reorders keys preserving comments).

Adding a new handler:

1. Create `src/kompose/rules/my_check.py` with a function:
   ```python
   from kompose._engine import Issue, LintContext

   def check(ctx: LintContext, params: dict, exclude: set[str]) -> list[Issue]:
       # use ctx.content (raw str), ctx.parsed (dict), ctx.globals (dict)
       return [Issue(message="...")]
   ```
2. Reference it from `rules.yaml`:
   ```yaml
   - name: my-check
     category: security
     handler: my_check
     params:
       ...
   ```

The handler signature is invoked once per service. `LintContext` exposes:

| Field | Type | Description |
|-------|------|-------------|
| `service_name` | `str` | Service directory name (e.g. `paperless`) |
| `compose_path` | `Path` | Path to the `compose.yml` |
| `content` | `str` | Raw text of `compose.yml` |
| `parsed` | `dict` | Parsed YAML (via PyYAML) — `{}` if parsing failed |
| `globals` | `dict` | Globals from the YAML config |

#### Host-wide checks via the `notices()` hook

Most rules are per-service, but some checks examine the host as a whole
(e.g. consistency between the root `compose.yml` includes and the service
dirs on disk). A handler may export an optional `notices()` function which
the engine invokes once per lint run:

```python
def notices(host_dir: Path, services: list[Path], params: dict, exclude: set[str]) -> list[Issue]:
    # one-shot, host-wide check
    return [Issue(message="...", location="compose.yml")]
```

Notices appear in a separate **Notices** section after the per-service
details. They contribute to the global error/warning counts and to the
final exit code.

#### Auto-fix via the `fix()` hook

A rule may also export an optional `fix()` function that auto-corrects the
issues it detects. The convention mirrors `check()` and `notices()`:

```python
from kompose._engine import FixApplied, LintContext

def fix(ctx: LintContext, params: dict, exclude: set[str],
        *, force: bool = False, dry_run: bool = False) -> list[FixApplied]:
    # mutate ctx.compose_path (unless dry_run) and return what changed
    return [FixApplied(target="paperless/compose.yml", message="reordered properties in app")]
```

For built-in types, the companion function is `<type>_fix` (e.g.
`property_order_fix` in `rules/_builtin.py`).

`FixApplied` carries:

| Field | Description |
|-------|-------------|
| `target` | Human path (e.g. `paperless/compose.yml`) shown in the summary |
| `message` | Short description (e.g. `reordered 4 properties`) |
| `before`, `after` | Optional snippets for `--dry-run` preview (unused so far) |

The rule itself is responsible for honoring the keyword args:

- `force=True` → skip confirmation prompts, apply defaults to ambiguous choices
- `dry_run=True` → describe what *would* be done, but do not mutate disk

`kompose fix` runs every rule's `fix()` hook across all services, then
chains `cmd_env_fix` (interactive). In `--dry-run`, the env fix step is
skipped (it's interactive by design). `kompose check` appends a footer
counting the issues that have a `fix()` available:

```
→ 4 auto-fixable. Run `kompose fix` to apply.
```

**Invariant — `fix()` must align with `check()`**

Every rule's `fix()` MUST use the same predicate as its `check()`:

- If `check(ctx, …)` returns `[]` → `fix(ctx, …)` MUST return `[]`
- If `check(…)` reports issues → `fix(…)` may attempt to correct them

A fix that touches a file `check` considers clean is a bug — never reorder
or mutate things that aren't explicitly flagged. Reuse the same predicate
helpers in both functions, and add a regression test that creates a
clean-by-check input and asserts `fix(…) == []`.

## Environment files

### Sync logic

`.env` is the structural reference. `.env.example` is rebuilt to match it.

**`build_example_content` — line-by-line rebuild of `.env.example` from `.env`:**

```
for each line in .env:
  ├─ KEY=value          → KEY={.env.example[KEY] or ''}
  ├─ # KEY=value        → # KEY={.env.example commented[KEY] or ''}
  └─ comment / blank    → copied as-is
```

Active vars and commented-out vars follow the same rule: preserve the existing
`.env.example` value if present, otherwise default to `''`.

**`cmd_env_sync` — full sync flow:**

```
.env exists?
├─ NO   → create .env from .env.example
│
└─ YES  → diff active keys between .env and .env.example
          │
          ├─ only in .env
          │   → ask: add to .env.example (as '') OR remove from .env
          │
          ├─ only in .env.example
          │   → ask: add to .env OR remove from .env.example
          │
          └─ rebuild_example()
              → rebuild .env.example from .env via build_example_content
              → aligns: order, comments, blank lines, sanitizes secrets
```

### `kompose env fix`

Interactive synchronization of `.env` and `.env.example` files. The
standalone command for env drift detection has been removed — use
`kompose check` for the read-only diagnostic (the `env_check` lint rule
surfaces drift in the unified lint table). Use `env fix` to actually
apply changes.

**Creation** — If `.env.example` exists but `.env` does not, `.env` is created as a copy
of `.env.example`.

**Variable sync** — For each service with differences, asks what to do:

- Variables in `.env` but not `.env.example`: add to `.env.example` (with `''` value) or remove from `.env`
- Variables in `.env.example` but not `.env`: add to `.env` or remove from `.env.example`

Use `-f` / `--force` to skip confirmation (defaults: add to `.env.example`, add to `.env`).

**Structure sync** — After variable reconciliation, `.env.example` is automatically rebuilt
to match `.env`'s structure. `.env` is the reference for comment lines, blank
lines, and variable ordering. Only values differ: `.env` has real values,
`.env.example` has placeholder values (or `''`).

## Status

```bash
kompose status          # Compact view
kompose status --stats  # With memory usage
```

The `--stats` (`-s`) flag adds a memory column showing percentage usage per container.
Containers with a custom memory limit show `pct%/limit` (e.g. `34%/2G`).
Colors indicate usage: green < 50%, yellow 50-80%, red >= 80%.

## Development

### Layout

```
packages/kompose/
  pyproject.toml
  README.md
  src/
    kompose/
      __init__.py              # version
      __main__.py              # CLI entry point (kompose script)
      _engine.py               # rule loading, dispatch, types
      compose.py               # kompose up/down/restart/logs/status
      config.py                # paths, host helpers
      env.py                   # kompose env fix (formerly env sync)
      lint.py                  # kompose check orchestrator (formerly lint)
      fix.py                   # kompose fix orchestrator (rule fixes + env fix chain)
      utils.py                 # Colors, Table, confirm()
      rules/
        __init__.py
        _builtin.py            # substring_required, substring_forbidden, property_order
        traefik_router_naming.py
        traefik_middleware_correlation.py
        reverse_proxy_network.py
  examples/
    rules.yaml                 # ready-to-copy lint config
  brew/
    kompose.rb                 # draft Homebrew formula
    README.md
  tests/
    test_compose.py
    test_config.py
    test_engine.py
    test_env.py
    test_lint.py
    fixtures/
```

### Running tests

```bash
# from packages/kompose/
~/.local/pipx/venvs/kompose/bin/python -m unittest discover tests -v

# single file
~/.local/pipx/venvs/kompose/bin/python -m unittest discover tests -v -p test_lint.py
```

The `tests/__init__.py` adds `src/` to `sys.path`, so tests can run without
the package being installed. When pipx-installed, this is a no-op.
