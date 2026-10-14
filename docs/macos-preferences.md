# Tracking macOS app preferences

How this repo backs up and restores macOS application settings (Terminal,
iTerm2, Rectangle, Open Island, …) without the usual `chezmoi status` noise.

## The problem

The obvious approach — track the live plist directly:

```
~/Library/Preferences/com.apple.Terminal.plist  ->  chezmoi source
```

…doesn't work well. Apps rewrite their plist **constantly** (window position,
"last opened", Sparkle update timestamps, ephemeral UI state), so the tracked
file is *always* dirty. `chezmoi status` shows a permanent `MM`, and every
`chezmoi re-add` captures noise. chezmoi is one-way (source → target); a file
the app keeps rewriting diverges forever.

## The approach

Track a **stable, encrypted snapshot** per app instead of the live plist, and
re-apply it with `defaults import` (which goes through `cfprefsd`, the correct
way — unlike editing `~/Library/Preferences` directly).

```
                              pac preferences save
  live domain  ── defaults export ──►  ~/.config/macos-preferences/<domain>.plist
  (cfprefsd)                                   │ chezmoi re-add (encrypt)
                                               ▼
                        dot_config/macos-preferences/encrypted_<domain>.plist.age   (repo)
                                               │ chezmoi apply
                                               ▼
                              ~/.config/macos-preferences/<domain>.plist            (stable mirror)
                                               │ run_onchange: defaults import
                                               ▼
  live domain  ◄──────────────────────  applied back into the app's defaults
```

The live `~/Library/Preferences/<domain>.plist` is **never tracked**, so it
never appears in `chezmoi status`. The snapshot lives under
`~/.config/macos-preferences/`, where nothing but chezmoi writes — so it stays
clean too. You capture changes explicitly (`pac preferences save`), not on the
app's schedule.

## Components

| Path | Role |
|---|---|
| `home/.chezmoidata/macos-preferences.yaml` → `macos_preferences_domains` | The list of tracked domains. Drives the import script. |
| `home/dot_config/macos-preferences/encrypted_<domain>.plist.age` | The encrypted snapshot (source). Applied to `~/.config/macos-preferences/<domain>.plist`. |
| `home/.chezmoiscripts/darwin/run_onchange_after_import-macos-preferences.sh.tmpl` | Re-applies each snapshot with `defaults import`. |
| `home/.chezmoiignore.tmpl` | Allowlists `.config/macos-preferences`. The live `Library/Preferences/*.plist` are **not** in the allowlist, so they are unmanaged. |
| `pac preferences …` ([owpac/pac](https://github.com/owpac/pac)) | The CLI to list / save / remove tracked preferences. `bootstrap-tools` installs it with uv, and writes its zsh completion (subcommands + slug/domain). |

## The import script

`run_onchange_after_import-macos-preferences.sh.tmpl` is a chezmoi
`run_onchange_after_` script (runs after files are applied, on macOS, non-minimum):

- It embeds a **sha256 of each snapshot's *decrypted* content**, so chezmoi re-runs it
  *only* when the real content of a snapshot changes. It does not re-run on every apply,
  or when age re-encryption alone produces a different ciphertext.
- It imports **only the snapshots that changed since their last import**.
  `~/.local/state/macos-preferences/<domain>.sha256` keeps the hash of the last import of
  each domain. So a new snapshot of one app does not reset the other apps, and a change to
  the script itself imports nothing.
- On a new machine, there is no state yet, so the script imports every snapshot.

```sh
import() {   # domain, sha256 of the decrypted snapshot
  [ "$(cat "$state/$domain.sha256" 2>/dev/null || true)" = "$hash" ] && return 0
  defaults import "$domain" "$HOME/.config/macos-preferences/$domain.plist"
  echo "$hash" > "$state/$domain.sha256"
}
{{ range .macos_preferences_domains -}}
import "{{ . }}" "{{ include (printf "dot_config/macos-preferences/encrypted_%s.plist.age" .) | decrypt | sha256sum }}"
{{ end -}}
```

To import a snapshot again by hand, run
`defaults import "<domain>" ~/.config/macos-preferences/<domain>.plist`. chezmoi does not
re-run the script for that: the content of the script does not change.

## Keys that the apps change on their own

Apps also write keys that are not settings: window positions (`NSWindow Frame *`), panels
(`NSNav*`), update checks (`SULastCheckTime`), app versions (`iTerm Version`), dates
(`LastTerminalStartTime`) and the local state of iTerm2 (`NoSync*`). These keys change
without a real change of settings.

`pac preferences save` removes them from each snapshot before it adds the snapshot. The
patterns are in `home/.chezmoidata/macos-preferences.yaml` → `macos_preferences_ignored_keys`
(shell patterns, for every domain). The snapshot is an XML plist with sorted keys. So a
snapshot changes only when a real setting changes, and the other machines re-import an app
only after a real change.

- `defaults import` merges the top-level keys of the snapshot into the domain, so the ignored
  keys stay on each machine.
- The filter removes top-level keys only. `defaults import` replaces each top-level value
  whole, so removing a nested key would also remove it from the machine. For example,
  `ProfileCurrentVersion` stays in each Terminal profile: it changes only when a macOS
  update changes the format of the profiles.
- If a new key changes on its own, add its pattern to the list, then run
  `pac preferences save <app>`.
- iTerm2 copies each dynamic profile into `New Bookmarks`. `pac preferences save` removes
  these copies, because the files in `~/Library/Application Support/iTerm2/DynamicProfiles`
  (managed by chezmoi) are the source of these profiles.

## Usage — `pac preferences`

```
pac preferences list                 # slug -> domain of everything tracked
pac preferences save [name...]       # snapshot: all tracked, or specific ones
pac preferences remove <name...>     # stop tracking (keeps the app's live prefs)
```

- **name** is a *slug* (last dot-component, lowercased — e.g. `terminal`,
  `iterm2`, `rectangle`, `openisland`) or a full domain (`com.apple.Terminal`,
  with or without a trailing `.plist`).
- `save` with no args re-captures every already-tracked app.
- After any `save`/`remove`, review and commit the source repo:
  `chezmoi cd` → `git add -p && git commit`.

### Add a new app

```
pac preferences save com.foo.Bar
```

This exports the domain, adds the encrypted snapshot to the source, **and
auto-registers the domain** in `home/.chezmoidata/macos-preferences.yaml`. On the next
`chezmoi apply` (here and on other machines after a pull) the import script
applies it. Nothing to edit by hand.

### Stop tracking an app

```
pac preferences remove terminal
```

Removes it from `macos_preferences_domains`, deletes the encrypted source
snapshot and the `~/.config/macos-preferences/` mirror. The app's **live**
preferences in `~/Library/Preferences/` are left untouched.

## Which apps are worth tracking

Only apps whose configuration actually lives in their plist:

| Track | Because |
|---|---|
| Terminal, iTerm2 | The plist *is* the full config (profiles, colors, keys). |
| Rectangle | Shortcuts / gaps live in the plist. |
| Open Island | Island appearance/behavior, feature toggles, agent integrations. |

Do **not** track apps that keep their real config elsewhere:

| Skip | Because |
|---|---|
| Raycast | Config is in its app-support DB + cloud sync + a `.rayconfig` export. |
| Slack | Settings are server-side; the plist is ephemeral window state. |

## Caveats

- `defaults import` writes through `cfprefsd`; a **running** app may need a
  restart to pick up the imported values.
- Some plists carry ephemeral keys (window frames, Sparkle updater timestamps).
  They're harmless to restore, but a re-`save` will always show a diff — it's
  never a perfect no-op.
- `save` skips a domain that `defaults read` can't find (e.g. a typo, or an app
  whose prefs are sandboxed and unreadable this way).
