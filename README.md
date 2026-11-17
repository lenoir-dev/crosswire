# crosswire

Find likely semantic conflicts between Python changes on parallel Git branches before merging.

## Quickstart (about two minutes)

From this checkout, with [uv](https://docs.astral.sh/uv/), Python 3.11+ and Git 2.38+ installed:

```sh
uv tool install .
demo_dir=$(mktemp -d)
cd "$demo_dir"
git init -q -b main
git config user.name Demo
git config user.email demo@example.invalid
printf 'def charge(amount): return amount\n' > billing.py
git add . && git commit -qm base
git switch -qc rename-charge
printf 'def create_charge(amount): return amount\n' > billing.py
git add . && git commit -qm rename
git switch -qc add-refunds main
printf 'import billing\nbilling.charge(10)\n' > refunds.py
git add . && git commit -qm caller
crosswire check --target main rename-charge add-refunds
```

The last command exits **1**, reporting CW001 at `refunds.py:2` and suggesting
`billing.create_charge`. Git can merge these branches textually; the new caller would
still refer to a removed function. `uv tool update-shell` adds the tool directory to PATH if your shell cannot find `crosswire`
(restart the shell afterward).

On the same demo:

```sh
crosswire check --target main --combined rename-charge add-refunds
crosswire plan --target main rename-charge add-refunds
```

Pairwise mode compares branch pairs. Combined mode checks the virtual integrated state,
including callers already on the target, and can explain repairs supplied by a third branch.
`plan` finds a safe order or an atomic group and lists branches it cannot place. These commands
leave refs, HEAD, the index and worktree unchanged; Git writes disposable virtual objects.

## Why

A clean Git merge only means the edits do not conflict textually. One branch can remove a
function while another adds a call to it, leaving the combined code broken. Crosswire compares
branch pairs before integration and points to the added code and the branch that changed its API.

Crosswire compares every pair of branches, so work grows quadratically with branch count. It
requires Python 3.11+ and Git 2.38+; runtime dependencies are limited to the Python standard library.

```sh
uv sync
uv run crosswire check [--repo PATH] [--base REF | --target REF] [--src DIR]... [--format text|json|github|sarif] [--no-textual] [--no-cache] BRANCH BRANCH [BRANCH...]
```

The default source roots are `src` followed by the repository root when `src/` exists at the
pair base; otherwise the repository root. Supply `--src` repeatedly to choose roots explicitly.
Crosswire detects removed references, incompatible calls to statically resolved signatures,
duplicate definitions, Django and literal Alembic migration collisions, and Git textual conflicts.
Dynamic Python and uncertain references are intentionally skipped. Exit status is 0 for no errors,
1 for findings at error severity, and 2 for invalid input or Git failure. Parse warnings go to stderr.
Git's merge-tree operation may write objects, but does not change refs, HEAD, the index or worktree.

## Rules

| Rule | Severity | Detects |
| --- | --- | --- |
| CW001 | error | A new reference to a symbol removed by another branch; a possible rename may be suggested. |
| CW002 | error | A new call incompatible with another branch's changed, statically known signature. |
| CW003 | warning | Different definitions of the same name added in both branches. |
| CW004 | error | Colliding Django migration numbers or literal Alembic `down_revision` values. |
| CW005 | error | Textual Git merge conflicts; disable with `--no-textual`. |

## Target and caching

Use `--target main` to summarize each branch against its merge base with the target. Pairwise
reports still show each pair's merge base. Without `--target`, each pair uses its own merge base;
`--target` and `--base` cannot be combined. Semantic checks skip pairs without overlapping
changes or references; textual conflict checks still run for every pair.

Summaries are cached under the shared Git directory at `crosswire/cache/v1/`; use `--no-cache`
to disable cache reads and writes. Cache files are disposable. `--format sarif` emits SARIF 2.1.0
for code-scanning tools; findings retain their branch labels in result properties.

### Composite action

After checking out with full history, use the repository containing `action.yml` as a composite
action. Configure `contents: read` and `pull-requests: read`; leave `branches` empty to fetch open
PR heads (including forks), or provide whitespace-separated refs. For example, when the action is
in the checked-out repository:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0
- uses: ./
  with:
    target: main
    format: github
```

## JSON output

Use `--format json` for machine-readable output. For example (the SHA is illustrative):

```json
{
  "coverage": "complete",
  "limitations": {},
  "findings": [
    {
      "branch": "add-refunds",
      "hint": "use `billing.create_charge`",
      "limitations": [],
      "line": 4,
      "message": "`billing.charge` is used here but was removed in rename-charge (renamed to `billing.create_charge`?)",
      "other_branch": "rename-charge",
      "path": "refunds.py",
      "rule": "CW001",
      "severity": "error",
      "symbol": "billing.charge"
    }
  ],
  "pairs": [{"a": "rename-charge", "b": "add-refunds", "base": "0123456789012345678901234567890123456789"}],
  "summary": {"errors": 1, "warnings": 0},
  "tool": "crosswire",
  "version": 1
}
```

## GitHub Actions

The following workflow fetches the head of every open pull request, including PRs from forks,
then checks each distinct commit against the others. It uses GitHub annotations for findings.
It skips the check when fewer than two distinct PR heads exist. For a scheduled workflow,
the check appears on the scheduled run rather than on individual pull requests.

```yaml
name: Crosswire
on:
  workflow_dispatch:
  schedule:
    - cron: '0 6 * * *'
permissions:
  contents: read
  pull-requests: read
jobs:
  crosswire:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v6
      - run: uv sync
      - name: Check open pull request branches
        shell: bash
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          set -euo pipefail
          gh api --paginate "repos/${GITHUB_REPOSITORY}/pulls?state=open&per_page=100" --jq '.[].number' > "$RUNNER_TEMP/crosswire-prs"
          mapfile -t numbers < "$RUNNER_TEMP/crosswire-prs"
          refs=()
          declare -A seen=()
          for number in "${numbers[@]}"; do
            ref="refs/crosswire/pr/$number"
            git fetch --no-tags origin "refs/pull/$number/head:$ref"
            sha=$(git rev-parse "$ref^{commit}")
            if [[ -z "${seen[$sha]+x}" ]]; then
              refs+=("$ref")
              seen[$sha]=1
            fi
          done
          if (( ${#refs[@]} >= 2 )); then
            uv run crosswire check --format github "${refs[@]}"
          else
            echo "Fewer than two distinct open PR heads; skipping."
          fi
```

## Demo

Run in a temporary directory with Git user name and email configured:

```sh
mkdir crosswire-demo && cd crosswire-demo
git init -b main
cat > billing.py <<'PY'
def charge(amount, currency):
    return amount
PY
git add billing.py && git commit -m base
git switch -c rename-charge
cat > billing.py <<'PY'
def create_charge(amount, currency):
    return amount
PY
git add billing.py && git commit -m rename
git switch main
git switch -c add-refunds
cat > refunds.py <<'PY'
import billing

def refund():
    return billing.charge(10, "USD")
PY
git add refunds.py && git commit -m refunds
git merge-tree --write-tree rename-charge add-refunds
crosswire check rename-charge add-refunds
```

The merge is textually clean, but crosswire exits 1 and reports CW001 with `create_charge` as a
possible rename. Run `uv run crosswire` from this project with `--repo /path/to/crosswire-demo`
if crosswire is not installed on your PATH.

## Checking 3+ branches together

Use `crosswire check --target main --combined branch-a branch-b branch-c` to analyze the
virtual result of integrating a set of branches in the given order. CW006 identifies a broken
reference caused by a combination of changes; single-branch causes use CW001 or CW002. A
pairwise conflict repaired by another integrated branch is reported as a warning. Textual
conflicts skip the affected branch. Git creates unreferenced virtual objects without modifying
refs, the index, or the worktree. Use `--format json` for the version 2 combined report.

## Plan a merge order

Run `crosswire plan --target main branch-a branch-b branch-c` to find a safe sequence.
The planner checks references already on the target, preserves branch ancestry, and can
recommend merging a small group together when only the combined state is safe. A blocked
branch includes its findings and a hint when one is available. Use `--format json` for
steps, blockers, containment and coverage. Bounded coverage means some combinations were
not checked and must not be assumed safe.

## Diagnostics and stable JSON

`--format json` uses version **1** for pairwise checks and **2** for combined checks and plans.
Every finding has `hint` (a string or null) and `limitations` (a list of strings).
N-way findings also have `repro`: a shell-quoted command with the exact target and all supplied
`--src` roots when an exact minimal culprit set is known, otherwise null. It preserves the
original integration order and includes `--repo` exactly as supplied. Absolute repository paths
work from any directory; relative paths retain the original working-directory assumption. A target-caused failure names the target in `culprits` and may reproduce with only
one branch. Hints are evidence-based: keyword advice requires a keyword-capable parameter,
and Django renumbering considers the merged migration directory.

All report formats expose `coverage` and report limitations. `complete` means no known gaps in
the supported static analysis; `partial` means an in-scope site was skipped or could not be resolved;
`bounded` means a search bound was hit. Coverage considers changed files, consulted modules and
relevant target callers. Unsupported constructs count only in changed files; unchanged unrelated
code is outside this scope. Stdlib and third-party imports are out of scope and do not make coverage
partial. When both apply, coverage is `bounded` and the limitations
still describe skipped sites. Each category counts distinct `(path, line, construct)` sites across
the requested states, with at most five deterministic examples. Internal culprit and planner
trials do not inflate those counts. Coverage never changes the exit code: 0 for no errors,
1 for error findings (or blocked plan branches), 2 for usage, Git or internal errors.

JSON versions stay at 1 and 2 as optional fields are added. Consumers should accept unknown keys;
new fields are optional in the schemas with defaults (`hint`/`repro`: null, finding `limitations`:
`[]`, report `limitations`: `{}`, `coverage`: `complete` for older reports). The offline Draft
2020-12 schemas ship in both the wheel and source distribution:

```sh
crosswire schema --version 1
crosswire schema --version 2
crosswire schema --version 2 --mode plan
```

Finding limitations identify uncertainties such as an inexact culprit set or a location from a
branch tip. UTF-8 is decoded strictly; a literal U+FFFD in valid UTF-8 is ordinary source text.

Python source blobs larger than 2 MB (2,000,000 bytes), binary or non-UTF-8 sources, parse failures, submodules,
unsupported dynamic constructs and unresolved references appear in limitations. Submodules are
never initialized. Bare repositories and detached HEADs work when the requested refs exist.
Unborn repositories and shallow clones produce an actionable error; fetch full history first
(`git fetch --unshallow` for a shallow clone).
