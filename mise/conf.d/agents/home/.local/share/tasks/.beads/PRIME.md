# Beads: the rules of the tasks

Beads (`bd`) tracks all the work. This text replaces the default text of `bd prime`. AGENTS.md takes precedence over this text.

<!-- Source: owpac/dotfiles, mise/conf.d/agents/home/.local/share/tasks/.beads/PRIME.md. The group agents of mise links it into the home workspace. `bd prime --export` gives the default text of bd. -->

## Workspace

- All the tasks are in the home workspace, `~/.local/share/tasks`. Their ids start with `task-`.
- `BEADS_DIR` points to this workspace in the shell, in Claude Code and in Codex. Thus `bd` finds the workspace from each directory, repositories included.
- If `bd` does not find the workspace, put `BEADS_DIR="$HOME/.local/share/tasks/.beads"` before the command.
- Do not run `bd init` or `bd setup`. Do not create a workspace in a repository. The permission rules of Claude Code and Codex block these commands.
- Do not run `bd edit`: it opens an editor, and the agent stops.

## Commands

```bash
bd ready -l repo:<name>           # the tasks of a repository with no blocker
bd list -l repo:<name>            # all the tasks of a repository
bd show <id>                      # details, notes, comments and dependencies
bd search <query>                 # find a task by keyword
bd create --title "…" --type task --priority 2 --labels repo:<name>,owner:<owner> --description "…"
bd create … --parent <id>         # a child task
bd update <id> --claim            # claim the task: you are the assignee, status in_progress
bd note <id> "…"                  # add a progress note
bd update <id> --external-ref <url>        # the URL of the pull request
bd update <id> --set-metadata <key>=<value>
bd dep add <task> <blocker>       # <task> waits for <blocker>
bd defer <id> --until <date>      # defer the task to a date
bd defer <id>                     # defer the task with no date: the icebox
bd undefer <id>                   # open a deferred task again
bd close <id> --reason "…"        # the task is done or rejected
```

- Types: `task`, `bug`, `feature`, `epic`, `chore`. Priorities: 0 (critical) to 4 (the lowest), 2 by default.

## Labels

- Label each task about a repository `repo:<name>`. `<name>` is the repository name of its `origin` remote, for example `repo:prompts`.
- Also label each task about a repository `owner:<owner>`. `<owner>` is the account or the organization of its `origin` remote, for example `owner:doctolib` or `owner:owpac`.
- A task about more than one repository gets one `repo:` label for each repository, and one `owner:` label for each different owner.
- A task about no repository gets no `repo:` label and no `owner:` label.
- Do not add an `owner:` label to the tasks with the label `inbox` or `follow`. pac takes their owner from `external_ref`.

## Descriptions

- Write the description of a task on more than one line. One long line is difficult to read.
- Put one idea on each line. Use a numbered list for steps, a `-` list for items, and a blank line between sections.
- Give a description of more than one line with a heredoc:

  ```bash
  bd create --title "…" --description "$(cat <<'EOF'
  …
  EOF
  )"
  ```

## Life of a task

### States

A task has one of these states:

- Open (status `open`, `in_progress` or `blocked`): to do. The open tasks and the deferred tasks are the backlog.
- Deferred with a date (`bd defer <id> --until <date>`, status `deferred`): to do from this date. After this date, bd opens the task again.
- Deferred with no date (`bd defer <id>`, status `deferred`): the icebox, to do when the user has time. The user read the task one time and decided to do it later. Thus it has less priority than the open tasks.
- Closed (status `closed`): done or rejected. The reason of `bd close` tells if the task is done or rejected.

A deferred task has the same life as an open task. An agent claims it, does the work, then closes it: done or rejected.

### Steps

1. Before you change code, make sure that a task exists for the work. If no task exists, create it.
2. If the task is deferred, run `bd undefer <id>` first. The user does not see this step.
3. Claim the task: `bd update <id> --claim`.
4. If earlier sessions worked on the task, read their context first: `bd show <id>` and `mem_search` on the task id.
5. Write the progress with `bd note <id> "…"`.
6. When you open a pull request, give its URL to the task: `bd update <id> --external-ref <url>`.
7. Close the task after the merge of its work: `bd close <id> --reason "…"`. Do not close a task while its pull request is open.

If the work of a task has no pull request, close the task when the work is complete.

If the user rejects the task, close it and give the reason: `bd close <id> --reason "…"`.

## Session link

- A `PostToolUse` hook of the plugin `beads` (`hooks/link-bd-session`) links your session to each task that you claim, note, comment, close or update.
- The hook records `<tool>:<session_id>` as a `transcript` provenance, and adds the id to the metadata `sessions.<tool>` of the task.
- Do not record the session yourself. The user finds and resumes it with `pac agent task <id>`.

## Memory and lists

- Do not use `bd remember` or `bd memories`. engram keeps the durable memory (AGENTS.md, section "Memory: engram").
- Do not use TodoWrite, TaskCreate or Markdown TODO lists. Beads holds all the tasks.

## Git

- bd does no git operation (`no-git-ops: true`). AGENTS.md and the skill `workflow:worktrees` give the rules for git.
