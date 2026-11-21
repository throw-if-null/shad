# Coral adherence — shad

```yaml coral
# The Coral version this project is audited against ([VER-3]). The generator resolves this
# record against the rule set of the checkout it runs from, and it refuses a mismatch.
targets: "0.10.0"

# One deployable app. There is no channel here for a system-scale rule to bind.
scales:
  - app

# The kernel applies without being listed. Everything else applies because it is named
# here ([VER-6]). This is the recommended configuration: the production baseline and one
# app profile. A key that is absent is not adopted.
adopts:
  production-baseline: true
  app-profile:
    - cli
  language-binding: []
  runtime-agent-profile: false

# Coral rules this project knowingly breaks, each inside one subtree ([VER-5]). A human
# records an entry; an agent flags the ambiguity and never writes one ([AGENT-4]).
exceptions: []

# Local rules Coral does not have, namespaced per [VER-4] and scoped to a path per [VER-5].
extensions:
  - rule: SHAD-1
    path: src/shad
    statement: >
      textual is imported only inside the panel app modules, git/panel.py and
      todo/panel/app.py. Every other module imports it lazily from inside a
      function, never at module scope.
    reason: >
      Coral has no rule confining a heavy optional UI dependency. Importing
      textual.app costs about 100ms, which every `shad projects` and `shad git
      sync` would otherwise pay. Touches module-boundary and dependency
      placement.
    upstream: not-a-candidate
  - rule: SHAD-2
    path: src/shad/git
    statement: >
      git output is read only from git's documented machine formats: plumbing
      commands and the stable scripting formats (`for-each-ref` and `log` with
      explicit `%`-formats, `status --porcelain=v2`). Every outcome is decided
      from exit codes. The default human-facing output is never parsed.
    reason: >
      Coral has no rule on parsing a third-party CLI. git's default output is
      gettext-translated, `fetch.output=compact` rewrites ref names, and `git
      branch` layout depends on terminal width, so only git's documented machine
      formats with explicit fields and exit codes are a stable contract. Touches
      the external-tool trust boundary.
    upstream: not-a-candidate
```
