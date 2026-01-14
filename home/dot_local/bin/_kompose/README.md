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
| `up [service]` | Start services |
| `down [service]` | Stop services |
| `restart [service]` | Restart services |
| `logs <service>` | View service logs |
| `status` | Show services status with IPs |
| `lint [service]` | Check compose.yml files |
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
kompose restart immich        # Restart specific service
kompose logs paperless        # View logs (follow mode)
kompose logs paperless -n 50  # View last 50 lines
kompose status                # Show services with IPs
kompose lint                  # Lint all compose.yml
kompose env sync              # Sync all .env files
kompose env sync -f           # Sync without confirmation
kompose --host other up       # Use different host directory
```

## Configuration

### .komposeignore

Exclude services/routers from lint checks:

```yaml
exclude:
  routers:
    - my-router        # Exclude from router naming check
  middlewares:
    - my-router        # Exclude from middleware check
  logging:
    - my-service       # Exclude from logging check
  network:
    - my-service       # Exclude from network check
```

## Development

### Structure

```
_kompose/
  __init__.py      # Version
  config.py        # Configuration, paths, load_config()
  utils.py         # Colors, Table, confirm()
  lint.py          # kompose lint
  env.py           # kompose env sync
  compose.py       # kompose up/down/restart/logs/ps
  tests/
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
