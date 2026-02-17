"""Env commands for checking and synchronizing .env files."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import get_host_dir, get_services
from .utils import Colors, Table, confirm


@dataclass
class EnvSyncResult:
    service: str
    action: str
    target: str
    variables: list[str] = field(default_factory=list)


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse .env file into dict, preserving order."""
    env = {}
    if not path.exists():
        return env
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line, re.IGNORECASE)
            if match:
                env[match.group(1)] = match.group(2)
    return env


def read_env_lines(path: Path) -> list[str]:
    """Read .env file as list of lines."""
    if not path.exists():
        return []
    return [line.rstrip() for line in path.read_text().splitlines()]


def find_insert_position(lines: list[str], new_key: str, reference_keys: list[str]) -> int:
    """Find best position to insert a new key based on prefix matching."""
    prefix = ""
    for i in range(len(new_key)):
        if new_key[i] == "_":
            prefix = new_key[:i+1]

    last_match_idx = -1
    for i, line in enumerate(lines):
        if line.startswith("#") or not line.strip():
            continue
        match = re.match(r"^([A-Z_][A-Z0-9_]*)=", line, re.IGNORECASE)
        if match:
            key = match.group(1)
            if prefix and key.startswith(prefix):
                last_match_idx = i

    if last_match_idx >= 0:
        return last_match_idx + 1
    return len(lines)


def add_vars_to_env_file(path: Path, vars_to_add: dict[str, str], source_keys_order: list[str]) -> None:
    """Add variables to env file at appropriate positions."""
    lines = read_env_lines(path)

    for key in source_keys_order:
        if key not in vars_to_add:
            continue
        value = vars_to_add[key]
        new_line = f"{key}={value}"

        existing_keys = []
        for line in lines:
            match = re.match(r"^([A-Z_][A-Z0-9_]*)=", line, re.IGNORECASE)
            if match:
                existing_keys.append(match.group(1))

        pos = find_insert_position(lines, key, existing_keys)
        lines.insert(pos, new_line)

    path.write_text("\n".join(lines) + "\n")


def remove_vars_from_env_file(path: Path, vars_to_remove: set[str]) -> None:
    """Remove variables from env file."""
    lines = read_env_lines(path)
    new_lines = []

    for line in lines:
        match = re.match(r"^([A-Z_][A-Z0-9_]*)=", line, re.IGNORECASE)
        if match and match.group(1) in vars_to_remove:
            continue
        new_lines.append(line)

    path.write_text("\n".join(new_lines) + "\n")


def _parse_commented_vars(path: Path) -> dict[str, str]:
    """Parse commented-out env vars (# KEY=value) from a file."""
    commented = {}
    for line in read_env_lines(path):
        m = re.match(r"^#\s*([A-Z_][A-Z0-9_]*)=(.+)$", line, re.IGNORECASE)
        if m:
            commented[m.group(1)] = m.group(2)
    return commented


def build_example_content(env_path: Path, example_path: Path) -> str:
    """Build .env.example content matching .env's structure.

    Iterates .env line by line:
    - Commented-out env vars (# KEY=value) preserve .env.example value if it
      exists, otherwise sanitized to ''
    - Other comments and blank lines are copied as-is
    - Variables use existing .env.example values, or '' for new vars
    """
    example_vars = parse_env_file(example_path)
    example_commented = _parse_commented_vars(example_path)
    lines = read_env_lines(env_path)
    new_lines = []

    for line in lines:
        match = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line, re.IGNORECASE)
        if match:
            key = match.group(1)
            value = example_vars.get(key, "''")
            new_lines.append(f"{key}={value}")
        else:
            comment_match = re.match(r"^(#\s*)([A-Z_][A-Z0-9_]*)=(.+)$", line, re.IGNORECASE)
            if comment_match:
                prefix = comment_match.group(1)
                key = comment_match.group(2)
                value = example_commented.get(key, "''")
                new_lines.append(f"{prefix}{key}={value}")
            else:
                new_lines.append(line)

    return "\n".join(new_lines) + "\n" if new_lines else ""


def rebuild_example(env_path: Path, example_path: Path) -> bool:
    """Rebuild .env.example to match .env's structure. Returns True if changed."""
    new_content = build_example_content(env_path, example_path)
    old_content = example_path.read_text() if example_path.exists() else ""

    if new_content != old_content:
        example_path.write_text(new_content)
        return True
    return False


def ask_action(prompt: str, options: list[tuple[str, str]]) -> str | None:
    """Ask user to choose an action. Returns the key of the chosen option or None."""
    print(prompt)
    for i, (key, label) in enumerate(options, 1):
        print(f"  {Colors.CYAN}{i}{Colors.RESET}) {label}")
    print(f"  {Colors.GRAY}s{Colors.RESET}) Skip")

    try:
        response = input(f"{Colors.GRAY}>{Colors.RESET} ").strip().lower()
        if response == "s" or response == "":
            return None
        try:
            idx = int(response) - 1
            if 0 <= idx < len(options):
                return options[idx][0]
        except ValueError:
            pass
        return None
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def cmd_env_check(args) -> int:
    """Check .env files for differences with .env.example (read-only)."""
    service_name = getattr(args, "service", None)
    host = getattr(args, "host", None)
    host_dir = get_host_dir(host)

    if service_name:
        services = [host_dir / service_name]
        if not services[0].exists():
            print(f"{Colors.RED}Error: Service not found: {service_name}{Colors.RESET}")
            return 1
    else:
        services = get_services(host)

    table = Table(["Service", "Status", "Diff"])
    has_diff = False

    for service_dir in services:
        env_example = service_dir / ".env.example"
        env_file = service_dir / ".env"
        service = service_dir.name

        if not env_example.exists():
            continue

        example_vars = parse_env_file(env_example)
        env_vars = parse_env_file(env_file)

        if not env_file.exists():
            table.add_row([service, f"{Colors.RED}missing{Colors.RESET}", f".env not found ({len(example_vars)} vars in .env.example)"])
            has_diff = True
            continue

        only_in_env = set(env_vars.keys()) - set(example_vars.keys())
        only_in_example = set(example_vars.keys()) - set(env_vars.keys())

        # Check structural drift (comments, blank lines, order)
        expected = build_example_content(env_file, env_example)
        actual_lines = [l.rstrip() for l in env_example.read_text().splitlines()]
        actual = "\n".join(actual_lines) + "\n" if actual_lines else ""
        structure_drift = expected != actual

        if not only_in_env and not only_in_example and not structure_drift:
            table.add_row([service, f"{Colors.GREEN}ok{Colors.RESET}", f"{Colors.GRAY}-{Colors.RESET}"])
            continue

        has_diff = True
        diff_parts = []
        if only_in_env:
            diff_parts.append(f"{Colors.YELLOW}+{len(only_in_env)} .env only{Colors.RESET}")
        if only_in_example:
            diff_parts.append(f"{Colors.BLUE}+{len(only_in_example)} .env.example only{Colors.RESET}")
        if structure_drift and not only_in_env and not only_in_example:
            diff_parts.append(f"{Colors.GRAY}structure{Colors.RESET}")

        table.add_row([service, f"{Colors.YELLOW}drift{Colors.RESET}", ", ".join(diff_parts)])

    print()
    print(table.render())

    # Show detailed diffs
    for service_dir in services:
        env_example = service_dir / ".env.example"
        env_file = service_dir / ".env"
        service = service_dir.name

        if not env_example.exists() or not env_file.exists():
            continue

        example_vars = parse_env_file(env_example)
        env_vars = parse_env_file(env_file)

        only_in_env = sorted(set(env_vars.keys()) - set(example_vars.keys()))
        only_in_example = sorted(set(example_vars.keys()) - set(env_vars.keys()))

        if not only_in_env and not only_in_example:
            continue

        print(f"\n{Colors.BOLD}{service}{Colors.RESET}")
        if only_in_env:
            print(f"  In .env but not .env.example:")
            for key in only_in_env:
                print(f"    {Colors.YELLOW}{key}{Colors.RESET}")
        if only_in_example:
            print(f"  In .env.example but not .env:")
            for key in only_in_example:
                print(f"    {Colors.BLUE}{key}{Colors.RESET}")

    return 1 if has_diff else 0


def cmd_env_sync(args) -> int:
    """Execute the env sync command."""
    service_name = args.service
    force = getattr(args, "force", False)
    host = getattr(args, "host", None)
    host_dir = get_host_dir(host)

    if service_name:
        services = [host_dir / service_name]
        if not services[0].exists():
            print(f"{Colors.RED}Error: Service not found: {service_name}{Colors.RESET}")
            return 1
    else:
        services = get_services(host)

    table = Table(["Service", "Status", "Changes"])
    sync_results: list[EnvSyncResult] = []

    for service_dir in services:
        env_example = service_dir / ".env.example"
        env_file = service_dir / ".env"
        service = service_dir.name

        if not env_example.exists():
            continue

        example_vars = parse_env_file(env_example)
        env_vars = parse_env_file(env_file)

        # Case 1: .env does not exist - create from .env.example
        if not env_file.exists():
            env_file.write_text(env_example.read_text())
            table.add_row([service, f"{Colors.GREEN}+ created{Colors.RESET}", f"{len(example_vars)} vars"])
            sync_results.append(EnvSyncResult(service, "created", ".env", sorted(example_vars.keys())))
            continue

        # Find differences in BOTH directions
        only_in_env = set(env_vars.keys()) - set(example_vars.keys())
        only_in_example = set(example_vars.keys()) - set(env_vars.keys())

        if not only_in_env and not only_in_example:
            # Variables match, but check structure
            if rebuild_example(env_file, env_example):
                table.add_row([service, f"{Colors.YELLOW}~ structure{Colors.RESET}", "synced .env.example"])
                sync_results.append(EnvSyncResult(service, "structure", ".env.example"))
            else:
                table.add_row([service, f"{Colors.GREEN}\u2713 synced{Colors.RESET}", f"{Colors.GRAY}-{Colors.RESET}"])
            continue

        changes = []

        # Variables in .env but not in .env.example
        if only_in_env:
            print(f"\n{Colors.BOLD}{service}{Colors.RESET}: variables in .env but not in .env.example:")
            for key in sorted(only_in_env):
                print(f"  {Colors.YELLOW}{key}{Colors.RESET}")

            if force:
                action = "add_to_example"
            else:
                action = ask_action(
                    f"What to do with {len(only_in_env)} variable(s)?",
                    [
                        ("add_to_example", f"Add to .env.example"),
                        ("remove_from_env", f"Remove from .env"),
                    ]
                )

            if action == "add_to_example":
                vars_to_add = {k: "''" for k in only_in_env}
                env_keys_order = list(env_vars.keys())
                add_vars_to_env_file(env_example, vars_to_add, env_keys_order)
                changes.append(f"+{len(only_in_env)} example")
                sync_results.append(EnvSyncResult(service, "to_example", ".env.example", sorted(only_in_env)))
            elif action == "remove_from_env":
                remove_vars_from_env_file(env_file, only_in_env)
                changes.append(f"-{len(only_in_env)} env")
                sync_results.append(EnvSyncResult(service, "removed_from_env", ".env", sorted(only_in_env)))
            else:
                changes.append(f"{len(only_in_env)} skipped")
                sync_results.append(EnvSyncResult(service, "skipped", ".env", sorted(only_in_env)))

        # Variables in .env.example but not in .env
        if only_in_example:
            print(f"\n{Colors.BOLD}{service}{Colors.RESET}: variables in .env.example but not in .env:")
            for key in sorted(only_in_example):
                print(f"  {Colors.BLUE}{key}{Colors.RESET}")

            if force:
                action = "add_to_env"
            else:
                action = ask_action(
                    f"What to do with {len(only_in_example)} variable(s)?",
                    [
                        ("add_to_env", f"Add to .env"),
                        ("remove_from_example", f"Remove from .env.example"),
                    ]
                )

            if action == "add_to_env":
                vars_to_add = {k: example_vars[k] for k in only_in_example}
                example_keys_order = list(example_vars.keys())
                add_vars_to_env_file(env_file, vars_to_add, example_keys_order)
                changes.append(f"+{len(only_in_example)} env")
                sync_results.append(EnvSyncResult(service, "to_env", ".env", sorted(only_in_example)))
            elif action == "remove_from_example":
                remove_vars_from_env_file(env_example, only_in_example)
                changes.append(f"-{len(only_in_example)} example")
                sync_results.append(EnvSyncResult(service, "removed_from_example", ".env.example", sorted(only_in_example)))
            else:
                changes.append(f"{len(only_in_example)} skipped")
                sync_results.append(EnvSyncResult(service, "skipped", ".env.example", sorted(only_in_example)))

        # Rebuild .env.example structure from .env
        if env_file.exists() and env_example.exists():
            if rebuild_example(env_file, env_example):
                changes.append("structure")
                sync_results.append(EnvSyncResult(service, "structure", ".env.example"))

        # Determine status
        if changes:
            status = f"{Colors.YELLOW}~ updated{Colors.RESET}"
            changes_str = ", ".join(changes)
        else:
            status = f"{Colors.GREEN}\u2713 synced{Colors.RESET}"
            changes_str = f"{Colors.GRAY}-{Colors.RESET}"

        table.add_row([service, status, changes_str])

    print()
    print(table.render())

    # Detailed output
    if sync_results:
        to_example = [r for r in sync_results if r.action == "to_example"]
        to_env = [r for r in sync_results if r.action == "to_env"]
        removed_from_env = [r for r in sync_results if r.action == "removed_from_env"]
        removed_from_example = [r for r in sync_results if r.action == "removed_from_example"]
        skipped = [r for r in sync_results if r.action == "skipped"]
        created = [r for r in sync_results if r.action == "created"]

        if created:
            print(f"\n{Colors.BOLD}Created{Colors.RESET}")
            for r in created:
                print(f"  {Colors.CYAN}{r.service}/.env{Colors.RESET}")
                for var in r.variables[:8]:
                    print(f"    {Colors.GREEN}+{Colors.RESET} {var}")
                if len(r.variables) > 8:
                    print(f"    {Colors.GRAY}+{len(r.variables) - 8} more{Colors.RESET}")

        if to_example:
            print(f"\n{Colors.BOLD}Added to .env.example{Colors.RESET}")
            for r in to_example:
                print(f"  {Colors.CYAN}{r.service}/.env.example{Colors.RESET}")
                for var in r.variables:
                    print(f"    {Colors.YELLOW}+{Colors.RESET} {var}")

        if to_env:
            print(f"\n{Colors.BOLD}Added to .env{Colors.RESET}")
            for r in to_env:
                print(f"  {Colors.CYAN}{r.service}/.env{Colors.RESET}")
                for var in r.variables:
                    print(f"    {Colors.GREEN}+{Colors.RESET} {var}")

        if removed_from_env:
            print(f"\n{Colors.BOLD}Removed from .env{Colors.RESET}")
            for r in removed_from_env:
                print(f"  {Colors.CYAN}{r.service}/.env{Colors.RESET}")
                for var in r.variables:
                    print(f"    {Colors.RED}-{Colors.RESET} {var}")

        if removed_from_example:
            print(f"\n{Colors.BOLD}Removed from .env.example{Colors.RESET}")
            for r in removed_from_example:
                print(f"  {Colors.CYAN}{r.service}/.env.example{Colors.RESET}")
                for var in r.variables:
                    print(f"    {Colors.RED}-{Colors.RESET} {var}")

        structure = [r for r in sync_results if r.action == "structure"]
        if structure:
            print(f"\n{Colors.BOLD}Structure synced{Colors.RESET}")
            for r in structure:
                print(f"  {Colors.CYAN}{r.service}/{r.target}{Colors.RESET}: aligned to .env")

        if skipped:
            print(f"\n{Colors.BOLD}Skipped{Colors.RESET}")
            for r in skipped:
                print(f"  {Colors.CYAN}{r.service}/{r.target}{Colors.RESET}")
                for var in r.variables:
                    print(f"    {Colors.GRAY}?{Colors.RESET} {var}")

    return 0
