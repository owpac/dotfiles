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

| Command | Description |
|---------|-------------|
| `up [service] [containers...]` | Start services |
| `down [service] [containers...]` | Stop services |
| `restart [service] [containers...]` | Restart services |
| `logs <service> [containers...]` | View service logs |
| `status` | Show services status with IPs |
| `lint [service]` | Check compose.yml files against declarative rules |
| `env check [service]` | Check .env drift (read-only) |
| `env sync [service]` | Sync .env files |

### Options

| Option | Description |
|--------|-------------|
| `-h, --help` | Show help |
| `-v, --version` | Show version |
| `--no-color` | Disable colored output |
| `--host HOST` | Override host (default: nas) |

### Examples

```bash
kompose up                    # Start all services
kompose up paperless          # Start specific service
kompose down servarr plex     # Stop specific container in a service
kompose restart servarr sonarr radarr
kompose logs paperless -n 50
kompose status                # Compact view
kompose status --stats        # With memory usage
kompose lint                  # Lint all compose.yml
kompose env check             # Check all .env drift (read-only)
kompose env sync -f           # Sync without confirmation
kompose --host other up       # Use different host directory
```

## Lint

```bash
kompose lint            # Lint all services
kompose lint servarr    # Lint specific service
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
Service   Structure  Traefik  Logging  Network
─────────────────────────────────────────────────
appA      -          -        -        -
appB      2          -        1        -
appC      -          1        -        1

appB
  property-order: radarr:42 move `image` before `container_name`
  logging-driver: missing 'driver: local'

appC
  traefik-router-naming: my-router (missing -private/-public)
```

Columns are derived from each rule's `category:`. Counts show error /
warning issues per category. Exit code is `1` when any `error`-severity issue
is reported.

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
| `property_order` | `order: [key, ...]` | container names (inside `services:`) to skip |

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

| Handler | Purpose | `exclude:` semantics |
|---------|---------|----------------------|
| `traefik_router_naming` | Public routers must use `-private`/`-public` suffix | router names |
| `traefik_middleware_correlation` | Public→wan@file, private→lan@file | router names |
| `reverse_proxy_network` | Service must use proxy network or `network_mode` | service names |

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

### `kompose env check`

Read-only check comparing `.env` and `.env.example` for each service.
Returns exit code 1 if any drift is found (usable in CI).

```
Service   Status  Diff
────────────────────────────────────
appA      ok      -
appB      drift   +2 .env only
appC      drift   +1 .env.example only
appD      drift   structure
```

| Value | Meaning |
|-------|---------|
| `-` | No differences |
| `+N .env only` | N variables exist in `.env` but not in `.env.example` |
| `+N .env.example only` | N variables exist in `.env.example` but not in `.env` |
| `structure` | Same variables, but comments, blank lines, or ordering differ |

### `kompose env sync`

Interactive synchronization of `.env` and `.env.example` files.

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
      env.py                   # kompose env check/sync
      lint.py                  # kompose lint orchestrator
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
