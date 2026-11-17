# crosswire

Find likely semantic conflicts between Python changes on parallel Git branches before merging.

## Why

A clean Git merge only means the edits do not conflict textually. One branch can remove a
function while another adds a call to it, leaving the combined code broken. Crosswire compares
branch pairs before integration and points to the added code and the branch that changed its API.

Crosswire compares every pair of branches, so work grows quadratically with branch count. It
requires Python 3.11+ and Git 2.38+; runtime dependencies are limited to the Python standard library.

```sh
uv sync
uv run crosswire check [--repo PATH] [--base REF] [--src DIR]... [--format text|json|github] [--no-textual] BRANCH BRANCH [BRANCH...]
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

## JSON output

Use `--format json` for machine-readable output. For example (the SHA is illustrative):

```json
{
  "findings": [
    {
      "branch": "add-refunds",
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
