# Kompose

CLI for managing Docker Compose services on the homelab.

## Installation

Installed via [pipx](https://pipx.pypa.io) in editable mode from this repo.
Two chezmoi scripts handle the lifecycle on `chezmoi apply`:

- `run_onchange_after_install-kompose.sh.tmpl` — re-runs `pipx install
  --editable --force` when `pyproject.toml` changes (heavy, ~5–10s).
- `run_onchange_after_regen-kompose-completion.sh.tmpl` — re-runs
  `kompose --completion zsh > _kompose` when `src/kompose/__main__.py`
  changes (cheap, <1s).

Lexical filename ordering (`install-` < `regen-`) guarantees install runs
first on the very first apply.

Manual install:

```bash
pipx install --editable ~/.dotfiles/packages/kompose --force
```

This creates an isolated venv at `~/.local/pipx/venvs/kompose/` with PyYAML
and shtab installed, and exposes `kompose` in `~/.local/bin/`. Code changes
in `~/.dotfiles/packages/kompose/src/` are picked up live (editable mode).

### Shell completion

Zsh completion is generated from the argparse parser (via
[shtab](https://github.com/iterative/shtab)) so it never drifts from the CLI.
The chezmoi script regenerates `~/.local/bin/completions/_kompose` on every
relevant code change. To regenerate manually:

```bash
kompose --completion zsh > ~/.local/bin/completions/_kompose
```

Dynamic completions are wired via small zsh helpers in the script's preamble:
service groups → `ls $WORKSPACE_DIR/$HOST/`, nested containers → `awk` on the
group's `compose.yml`, `--host` values → `ls $WORKSPACE_DIR/`. Override the
defaults with `KOMPOSE_WORKSPACE` and `KOMPOSE_HOST` env vars if needed.

A future Homebrew tap is drafted at `brew/` — see `brew/README.md`.

## Usage

```bash
kompose <command> [options]
```

### Commands

The CLI follows a **noun-verb** canonical form (`service <verb>`)
with short top-level aliases for daily use. Both forms are first-class.

**Top-level (daily ergonomics)**

| Command | Alias | Description |
|---------|-------|-------------|
| `up [service] [containers...]` | — | Start services |
| `down [service] [containers...]` | — | Stop services |
| `restart [service] [containers...]` | `r` | Restart services |
| `logs <service> [containers...]` | `l` | View service logs |
| `status [service]` | `st` | Show services status |
| `check [service]` | — | Lint compose.yml + env drift against declarative rules |
| `fix [service] [--auto\|--env]` | — | Apply fixes (compose auto-fixes + interactive env sync) |
| `upgrade [service] [--logs]` | — | Trigger image updates via watchtower's HTTP API |

**Canonical form**

| Command | Alias | Description |
|---------|-------|-------------|
| `service up\|down\|restart\|logs\|status [name] [containers...]` | `svc` | Service lifecycle |

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
kompose r sonarr radarr          # Restart by service name(s)
kompose down                     # Stop all services
kompose l paperless -n 50        # Tail last 50 log lines (l = logs)
kompose st                       # Rich table of all services (st = status)
kompose status traefik           # Filtered table + last 30 log lines
kompose status traefik -f        # Same, follow logs continuously
kompose status --stats -f        # Live refresh of CPU/Mem table
kompose check                    # Lint everything (compose + env)
kompose check paperless          # Lint a single service
kompose fix                      # All fixes: compose auto-fixes + env interactive sync
kompose fix --auto               # Only compose-level auto-fixes (skip env)
kompose fix --env                # Only interactive env sync (skip compose fixes)
kompose fix --dry-run            # Preview without applying
kompose upgrade                  # Trigger watchtower update on every container (confirms)
kompose upgrade paperless        # Same, scoped to one group's images
kompose upgrade -f               # Skip the confirmation prompt
kompose upgrade --logs           # Render the latest watchtower session (no trigger)
kompose service status           # Canonical form of `kompose status`
kompose --host other up          # Use different host directory
```

### Fix scopes

`kompose fix` covers two distinct correction layers and exposes scope flags
to invoke them independently:

| Invocation | Compose-level rule fixes | Interactive env sync |
|---|---|---|
| `kompose fix` (default) | ✓ | ✓ |
| `kompose fix --auto` | ✓ | — |
| `kompose fix --env` | — | ✓ |

`--auto` and `--env` are mutually exclusive. `--dry-run` previews the
compose-level fixes; the env sync step is always skipped in dry-run
(interactive by design).

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
| `env_check` | `.env` ↔ `.env.example` parity (vars + structure). Shares its check logic with `kompose fix --env`. | service names | via `kompose fix` (or `--env` for env-only) |

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

### `kompose fix --env`

Interactive synchronization of `.env` and `.env.example` files. The
standalone `kompose env fix` command has been removed in favour of the
scope flag — `kompose fix --env [service]` runs ONLY the env sync.
Use `kompose check` for read-only diagnostic (the `env_check` lint rule
surfaces drift in the unified lint table).

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
kompose status                    # Compact view (service / container / status / IP / ports)
kompose status --stats            # + CPU + Mem columns (snapshot)
kompose status --stats -f         # Live: refresh every 2s (Ctrl+C to exit)
kompose status --stats -f -i 1    # Live with custom refresh interval
kompose status traefik            # Drill-down: filter to traefik + tail last 30 log lines
kompose status traefik -f         # Drill-down + follow logs continuously
```

### Columns

| Column | Source | Format |
|---|---|---|
| `Service` | Group dir name (= `<host>/<dir>/compose.yml`) | — |
| `Container` | `com.docker.compose.service` label | Grey + tree glyph for "dependency" containers |
| `Status` | docker ps `Status` | Green=running, red=exited, yellow=other |
| `IP` | `docker network inspect reverse-proxy` | IPv4 address; `-` if not on proxy network |
| `CPU` (with `--stats`) | docker stats `CPUPerc` (= % of one core) | <50% green, 50-100% yellow, >100% red |
| `Mem (<total>)` (with `--stats`) | docker stats `MemUsage` | <50% green, 50-80% yellow, >=80% red; `pct%/limit` when a custom mem limit is set |
| `Ports` | docker ps `Ports`, target side only | Top 4 + `+N more`; `-` if no exposed ports |

### Live mode (`-f`)

`-f` has two distinct meanings depending on arguments:

- **Without a service arg** (`kompose status -f` or `kompose status --stats -f`) → **refresh the table** every `-i` seconds (default 2s). Implemented via a background `docker stats` streaming subprocess, so the CPU/Mem samples are always fresh (≤1s old). Ctrl+C to exit.
- **With a service arg** (`kompose status traefik -f`) → **follow logs** after the tail (existing drill-down behaviour, unchanged).

In live mode, the cursor is hidden during refresh and restored on exit. The header shows the timestamp + interval so you can see the table is alive.

## Upgrade

```bash
kompose upgrade                   # Trigger watchtower update on all containers (prompts)
kompose upgrade paperless         # Same, scoped to one group's images
kompose upgrade -f                # Skip the prompt on the global form
kompose upgrade --logs            # Render the last watchtower session (no trigger)
```

`kompose upgrade` calls watchtower's `POST /v1/update` synchronously. While it
waits, a background thread tails `docker logs -f watchtower --since <t0>` and
prints a compact line for each high-signal event (pull / stop / create /
start / cleanup / session done). The HTTP JSON response is used as the
authoritative final summary.

### Resolution

| Input | Action |
|---|---|
| `kompose upgrade` | Full update — no `image=` filter |
| `kompose upgrade <group>` | Reads `<host>/<group>/compose.yml`, extracts unique `image:` values, sends `?image=…&image=…`. Build-only and digest-pinned services are skipped silently. |
| `kompose upgrade <service>` | If the arg isn't a top-level dir, walks the root compose's `include:` map (same one used by `kompose up`) to find which group it lives in, then sends only that single service's image. |
| `kompose upgrade --logs` | No trigger. Reads `docker logs watchtower`, slices the last session (between the most recent "Received HTTP API update request" / "Running update on schedule" and the matching "Update session completed"), prints the same compact rendering. |

### Watchtower-side prerequisites

Watchtower must run with both flags set so the HTTP trigger and the cron
schedule coexist:

```env
WATCHTOWER_HTTP_API_UPDATE='true'
WATCHTOWER_HTTP_API_PERIODIC_POLLS='true'
WATCHTOWER_HTTP_API_TOKEN='<token>'
```

Without `WATCHTOWER_HTTP_API_PERIODIC_POLLS`, enabling `HTTP_API_UPDATE`
silently disables the periodic schedule.

### Discovery / override

| What | Default | Override |
|---|---|---|
| Token | `<host>/watchtower/.env::WATCHTOWER_HTTP_API_TOKEN` | — |
| Base URL | derived from `<host>/watchtower/compose.yml` — `services.watchtower.networks.<network>.ipv4_address` + port `8080` | `kompose.watchtower.url` |

The override lives in `<host>/.kompose/rules.yaml` (or `globals.yaml` in the
multi-file layout) as a top-level `kompose:` section, sibling of `globals:`
and `rules:`:

```yaml
kompose:
  watchtower:
    url: http://10.10.10.200:8080   # optional; absent → discover from compose.yml
    # port: 8080                    # optional; only used during compose discovery
```

This `kompose:` section is reserved for CLI-level settings — it is not
exposed to lint handlers (those still consume `globals:`).

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success (no `failed`, even when `skipped > 0`) |
| `1` | Partial — at least one container failed to update |
| `2` | Trigger failed (no token, no URL, HTTP non-2xx, network error) |
| `130` | Local Ctrl+C — the foreground exits but watchtower keeps running |

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
      env.py                   # env sync workflow (invoked by `kompose fix [--env]`)
      lint.py                  # kompose check orchestrator (formerly lint)
      fix.py                   # kompose fix orchestrator (rule fixes + env fix chain)
      status.py                # kompose status — formatters, stats sources, table + watch loop
      upgrade.py               # kompose upgrade — watchtower HTTP API trigger + log session view
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
    test_status.py
    test_upgrade.py
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
