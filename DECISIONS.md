# Decisions

Append-only. One row per decision. A reversed decision gets a new row that names the row it
supersedes.

| Date | Decision | Reason | Decided by | Revisit when |
|---|---|---|---|---|
| 2026-11-01 | A commit under the maintainer's identity is the maintainer's decision, including code an agent generates in a session the maintainer directs. An agent that works without that direction commits under its own identity, and its commits follow `[AGENT-2]` and `[AGENT-4]`. No commit carries generic tool attribution. | The commit identity names the person accountable for the decision. A separate identity makes autonomous work auditable. Rejected: agent attribution on commits from a directed session, because the maintainer made those decisions; generic tool attribution, because it names no one who decided. | Mirza Merdovic | An autonomous agent starts work in shad, or Coral states a different provenance requirement. |
