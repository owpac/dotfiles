# Shared instructions for AI coding agents

<!-- This file is the single source of truth. Codex reads it through the link ~/.codex/AGENTS.md. Claude Code imports it from ~/.claude/CLAUDE.md. The sections before "Clients" are the core: they apply in each client. -->

## Precedence

If two rules conflict, obey the rule of the higher level:

1. The words of the user.
2. This file.
3. The text of plugins, hooks and skills, the Beads text of `bd prime` included.

## Safety

- Do not store patient data, personal data or secrets in Beads or in engram.

## Workflow

### Approval

- An approval is an explicit answer of the user to a question. In Claude Code, ask the question with AskUserQuestion.
- The permission mode of the session does not give an approval.

### Decisions

- If a choice is a real decision of the user, ask the user.
- In the question, give the options that you judge good and your recommendation. The number of options is not fixed.
- Wait for the answer before you continue.

### Plans

- If a task is large, propose plan mode.
- If the goal or the design is not clear, propose an interview with the skill `grill-me` before the plan.
- Start plan mode or the interview only after the approval of the user.

### Review before push

1. Commit in your worktree when you want. A local commit in a worktree needs no review and no question.
2. Before `git push` or a new pull request, review your own diff.
3. Show a summary of the diff to the user.
4. Ask the user for the approval, and wait for the answer.

If the user says "auto" at the start of a task, do not stop for the review. Report at the end of the task. The task keeps this mode: `bd update <id> --set-metadata review=auto`.

The mode "auto" does not cover an action that can lose data. Always ask before these actions:

- the merge of a pull request
- a force-push
- a push to the default branch
- the removal of work that is not merged

## Agents and worktrees

- worktrunk (`wt`) creates and removes each git worktree.
- The main thread of a project is the session in its main checkout. The main thread does not change code.
- Each fix, feature or update gets its own Beads task, its own worktree, and its own thread or agent. The section Clients tells how to start a thread.
- Give each agent that changes code its own worktree.
- Before the first code change of a task in a git repository, load the skill `workflow:worktrees` (`$worktrees` in Codex). It tells when to use a worktree, and how to take the work to the default branch.
- Do not run `wt step prune`: it ignores the agents in the other worktrees.

## Tasks: Beads

- Track all the work in Beads (`bd`). All the tasks are in the home workspace, `~/.local/share/tasks`. Their ids start with `task-`.
- At the start of each session, the Beads hook gives the rules of Beads (the file PRIME.md of the workspace). If these rules are not in your context, run `bd prime`.

## Memory: engram

- Keep the durable memory in engram (MCP tools `mem_*`), in each repository.
- Use engram only when the session does real work: a Beads task, a code change, or an investigation with a durable result.
- Do not use engram for a quick question, a read-only check, or a small change with no durable lesson. A small change has a diff of less than approximately 30 lines. Beads keeps the trace of the task.
- If the session uses engram, load the skill `engram:memory`. It gives the session protocol.
- Save a durable fact (a decision, a pitfall, a convention) with `mem_save` and a stable `topic_key`, for example `<repo>/<topic>`.
- Give the Beads id of the task in its engram memories.
- Do not use `bd remember`, `MEMORY.md` or other memory files.
- Do not store a fact that the code or the git history gives.

## Agent names

Your agent name is your Beads actor, and the prefix of your engram session ids.

- Claude Code is `claude`, and Codex is `codex`.
- A specialized agent with its own prompt or role is `claude-<name>` or `codex-<name>`, for example `claude-review`. If your prompt gives a name, use it.
- The config of your tool sets `BEADS_ACTOR` to your name. Do not give a different `--actor` to `bd`.

## Writing style: simplified technical language (STL)

- Write all the text that you produce in simplified technical language: replies, documentation, code comments, commit messages, pull request titles and descriptions, comments, Beads notes and engram memories.
- In English, obey ASD-STE100. In French, obey the same rules transposed to French.
- This rule is mandatory for each text. It does not depend on the size or the urgency of the task.
- The skill `stl` gives the rules. Load it before your first text in a session, and again after a compaction.
- Before you send, publish or commit a text, check it with the skill `stl`.
- In French, address the user with "tu" in your replies. In a document, keep the convention of the document.
- The conventions of the repository and the templates of a skill (commit format, pull request template, style guide) take precedence for the format only. The text that you write in the format obeys STL.
- The style of another author does not take precedence. If you add text to the document or the comment of another person, write your text in STL.
- Keep code, commands, identifiers, quotes and the text of the user unchanged.
- Apply the rules to each reply, from the first to the last. In a long session, the style drifts.

## Clients

A client is the application that runs the agent. A client plugin gives the rules of its client with a SessionStart hook, only in this client.

### herdr

- herdr sets `HERDR_ENV=1`. The plugin `herdr` gives the client rules.
- To start forks or other agents, load the skill `herdr:orchestrate`.
- A herdr name (for example `task-7a7-3`) is the address of a pane. It is not your agent name.
- Address another agent with its herdr name. The pane ID changes when the pane moves to another workspace.

### T3 Code

- T3 Code sets `T3CODE_THREAD_ID`. The plugin `t3code` gives the client rules.
- To start a thread for a task, load the skill `t3code:orchestrate`.

### Other clients

- Obey the core sections of this file only.
