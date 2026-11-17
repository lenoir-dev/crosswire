# N-way testability review (Sol)

1. Keep `commit-tree` chaining: it preserves real merge ancestry and Git ≥2.38 support.
   Freeze author/committer identity, timestamps, message bytes and parent order for virtual
   commits; user Git config must not affect OIDs or require a configured identity.
   Cache keys must include target state and integration policy/version; write no refs.
2. For ≤3 candidates, enumerate subsets by size, then sorted branch labels. This proves
   minimum cardinality and deterministic tie-breaking. ddmin only promises 1-minimality.
   For larger sets, document a bound and label approximate results rather than claiming minimal.
   Keep the reference-producing branch integrated during removal-candidate minimisation;
   otherwise removing the reference itself makes a broken subset appear clean.
3. Check the integrated state with CW005/CW006 and migration checks at every step.
   Historical pairwise CW001/CW002 cannot veto an intermediate state a compatibility branch
   has already fixed. Specify CW003 shadowing and CW004 multi-head semantics on the state.
   A “together” group needs an atomic state definition; sequential merging still exposes
   a broken intermediate state. Freeze whether textual conflicts block the whole group.
4. Extend RepoBuilder with named DAG nodes built from explicit parent SHAs, fixed metadata,
   and an oracle table: ordered subset → expected exported symbols, calls and conflicts.
   Three branches: A removes a def, B removes its guarded fallback, C adds a reference.
   Also put an existing target reference in that graph; each proper subset must remain valid.
   Three branches: A removes API, B supplies compatibility, C calls; compare all 6 orders,
   expected resolved_by and safe plan steps, including B before A.
   Four branches: add an unrelated decoy and competing fixes to test minimal-set tie-breaking.
   Five branches: stacked A→B plus independent removal/fix/caller; verify superseded labels,
   no duplicate application, deterministic blocked order and skipped-conflict exclusion.
   Add pre-existing broken tips, absent modules, re-export cycles, signature breaks,
   target-only callers and a textual-conflict branch whose changes must never enter I.
   Assert HEAD/index/worktree/refs unchanged, cache cold/warm identity and permutation
   behaviour explicitly: integration order can change I, whereas culprit arrays are sorted.
   Separate edited hunks and prove native merges clean; reserve textual conflicts for dedicated fixtures.
