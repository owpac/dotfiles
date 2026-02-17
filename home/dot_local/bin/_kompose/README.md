# Kompose

CLI for managing Docker Compose services on the NAS.

## Installation

The script is managed by chezmoi and deployed to `~/bin/kompose`.

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
| `lint [service]` | Check compose.yml files |
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
kompose down                  # Stop all services
kompose down servarr plex     # Stop specific container in a service
kompose restart servarr sonarr radarr  # Restart specific containers
kompose logs servarr plex     # View logs of a specific container
kompose logs paperless -n 50  # View last 50 lines
kompose status                # Show services with IPs
kompose status --stats        # Show services with memory usage (%)
kompose lint                  # Lint all compose.yml
kompose env check             # Check all .env drift (read-only)
kompose env sync              # Sync all .env files
kompose env sync -f           # Sync without confirmation
kompose --host other up       # Use different host directory
```

## Container targeting

When a compose file contains multiple services (e.g. `servarr` with plex, sonarr, radarr...),
you can target specific containers:

```bash
kompose up servarr plex         # docker compose ... up -d plex
kompose down servarr plex       # docker compose ... down plex
kompose restart servarr sonarr  # Restart only sonarr in servarr
kompose logs servarr radarr     # View radarr logs only
```

Without container arguments, the command applies to the entire compose project.

## Status

```bash
kompose status          # Compact view
kompose status --stats  # With memory usage
```

The `--stats` (`-s`) flag adds a memory column showing percentage usage per container.
Containers with a custom memory limit show `pct%/limit` (e.g. `34%/2G`).
Colors indicate usage: green < 50%, yellow 50-80%, red >= 80%.

## Lint

```bash
kompose lint            # Lint all services
kompose lint servarr    # Lint specific service
```

Checks `compose.yml` files against homelab conventions. Returns exit code 1 if issues are found.

```
Service   Order  Routers  Middlewares  Config
──────────────────────────────────────────────
appA      -      -        -           -
appB      2      -        1           -
appC      -      1        -           1
```

| Column | What it checks |
|--------|----------------|
| Order | Service properties must follow alphabetical order (`container_name`, `depends_on`, `env_file`, `environment`, `healthcheck`, `image`, `labels`, `logging`, `networks`, `ports`, `restart`, `user`, `volumes`) |
| Routers | Traefik router naming: when `owpac.com` (public) is used, routers must have a `-private` or `-public` suffix |
| Middlewares | Public routes (`owpac.com`) must use `wan@file`, private routes (`owpac.net`) must use `lan@file` |
| Config | Each service must have `logging: driver: local` and be on the `reverse-proxy` network (or use `network_mode`) |

Values: `-` = no issues, `N` = number of issues found.

Exclusions can be configured in `.komposeignore` (see [Configuration](#configuration)).

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

| Column | Description |
|--------|-------------|
| Service | Service directory name |
| Status | `ok` = in sync, `drift` = differences found, `missing` = .env does not exist |
| Diff | Details on the drift |

Diff values:

| Value | Meaning |
|-------|---------|
| `-` | No differences |
| `+N .env only` | N variables exist in `.env` but not in `.env.example` |
| `+N .env.example only` | N variables exist in `.env.example` but not in `.env` |
| `structure` | Same variables, but comments, blank lines, or ordering differ |

### `kompose env sync`

Interactive synchronization of `.env` and `.env.example` files.

**Creation** — If `.env.example` exists but `.env` does not, `.env` is created as a copy
of `.env.example`. This lets new services start with all required variables.

**Variable sync** — For each service with differences, asks what to do:

- Variables in `.env` but not `.env.example`: add to `.env.example` (with `''` value) or remove from `.env`
- Variables in `.env.example` but not `.env`: add to `.env` or remove from `.env.example`

Use `-f` / `--force` to skip confirmation (defaults: add to `.env.example`, add to `.env`).

**Structure sync** — After variable reconciliation, `.env.example` is automatically rebuilt
to match `.env`'s structure. `.env` is the reference for:

- Comment lines (`# Section header`)
- Blank lines (section separators)
- Variable ordering

Only values differ: `.env` has real values, `.env.example` has placeholder values (or `''`).

Example — given this `.env`:

```bash
# General
PUID=1000
PGID=1000

# Database
DB_HOST=prod.db.com
DB_PASS=s3cret
```

After sync, `.env.example` becomes:

```bash
# General
PUID=''
PGID=''

# Database
DB_HOST=''
DB_PASS=''
```

## Configuration

### .komposeignore

Exclude services/routers from lint checks:

```yaml
exclude:
  routers:
    - my-router
  middlewares:
    - my-router
  logging:
    - my-service
  network:
    - my-service
```

## Development

### Structure

```
_kompose/
  __init__.py      # Version
  config.py        # Configuration, paths, load_config()
  utils.py         # Colors, Table, confirm()
  compose.py       # kompose up/down/restart/logs/status
  env.py           # kompose env check/sync
  lint.py          # kompose lint
  tests/
    test_compose.py
    test_config.py
    test_env.py
    test_lint.py
    fixtures/
```

### Running tests

```bash
# All tests
python3 -m unittest discover _kompose/tests -v

# Specific file
python3 -m unittest _kompose/tests/test_lint -v

# Specific test
python3 -m unittest _kompose.tests.test_lint.TestFindRouterIssues.test_public_without_suffix
```
