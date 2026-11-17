# N-way implementability review — Terra

1. Use commit-tree chaining: merge-tree needs commit ancestry for correct recursive merge bases;
   synthetic commits supply that and work on Git 2.38. Freeze author/committer identity and dates,
   disable signing/hooks, and include metadata in cache identity for reproducible object IDs.
   Tree-only --merge-base is not equivalent to a sequence of actual merges.
2. Exhaustively enumerate subsets in stable input order through size 3; deterministic and easy to
   test. For larger candidates either explicitly report a non-minimal bounded result or use a
   documented deterministic ddmin fallback: ddmin guarantees only 1-minimality, not smallest size.
   Define which reference-bearing branch is always included and how textual conflicts affect trials.
3. Evaluate integrated-state CW005/CW006 at every step, plus CW003/CW004 where their non-reference
   effects remain relevant. Pairwise CW001/CW002 alone can wrongly block a state already repaired.
   Freeze the definition of “new” errors relative to T and prior steps, including pre-existing errors.
4. Use isolated real Git fixture repos with fixed commit metadata: 3–5 branches per scenario, clean
   and conflicting variants, order permutations, stacks, pre-existing errors, duplicate definitions,
   and exact integration/skipped/culprit assertions. Verify refs/index/worktree stay unchanged.

Hard points: Python imports are bindings, not proof a re-export resolves; follow chains with cycle
and ambiguity limits or classify unknown instead of claiming valid/broken. Guarded imports are
possible definitions, not guaranteed runtime definitions. Excluding conflicted branches changes
candidate sets and can make minimisation order dependent; fix a deterministic subset order and policy.
Merged reference locations can move or disappear: map or re-extract surviving occurrences, rather
than blindly reporting each branch summary's line. Textual conflict of a trial is not semantic proof.
A “merge together” group still has a sequential Git integration order; define whether intermediate
states may be broken and how the group is actually landed atomically. Stacked/superseded semantics
need an explicit rule for ancestor order and whether a contained branch is also separately reported.
