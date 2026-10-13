# Issue tracker

- Tracker: **GitHub Issues** on the private repository `MiguelCorre/escapadinha`.
- Specs: written as Markdown in `docs/specs/<date>-<slug>.md` (source of truth, versioned with the code) **and** opened as a GitHub issue of type *Spec* whose body links to the file and carries the user-story list. Tickets reference the spec issue.
- Tickets: one GitHub issue per ticket, title `<Mx> <imperative summary>` (e.g. `M1 Discover direct routes from the provider catalogue`). Body sections: *Ações do Miguel* (steps only he can do, in pt-PT), *Goal*, *Scope*, *Acceptance* (verifiable), *Verification* (commands), *Docs to update*. A ticket is independent and ≤ half a day of agent work.
- Milestones: GitHub milestones `M1 Data at scale`, `M2 Design`, `M3 Website`, `M4 Content`, `M5 Distribution`, `M6 Brand`.
- Commits reference the ticket (`Refs #12`); the PR or commit that completes it closes it (`Closes #12`).
- Conversation with Miguel is pt-PT; issues, code and commits are English (pt-PT where the content itself is Portuguese copy).
- Tooling: `gh` CLI, authenticated as Miguel.
