# Public R2 development gallery

These are scripted upstream-API oracle scaffolds, not natural upstream incidents.
The probe wraps a real upstream API object; original production/test sources remain covered.
Every example below has independently green target and tips. Positives fail only after a textually clean native integration; controls stay green.

| Case | Upstream | Family | Label | Branches |
| --- | --- | --- | --- | --- |
| `r2-public-0000` | `python-trio/sniffio@6996e05d9b9debe32f42f709c8041e744f850478` | remove_attribute | positive | A, B |
| `r2-public-0020` | `python-trio/sniffio@6996e05d9b9debe32f42f709c8041e744f850478` | required_keyword | positive | A, B |
| `r2-public-0040` | `python-trio/sniffio@6996e05d9b9debe32f42f709c8041e744f850478` | conjunctive | positive | A, B, C |
| `r2-public-0005` | `python-trio/sniffio@6996e05d9b9debe32f42f709c8041e744f850478` | from_import | compatible | A, B |

Recreate an example from its pinned upstream plus exact baseline and branch patches:

```sh
python -m eval.replay r2-public-0040 --destination NEW_DIRECTORY
crosswire check --repo NEW_DIRECTORY --target crosswire-target --combined A B C
```

The checker evidence and every single-removal attribution trial are in `cases.json`.
The conjunctive example retains one binding on A and one on B; only A+B+C breaks the newly added caller.
The hard-negative example replaces a direct definition with a star export and remains oracle/runtime green.
Private cases, selected identities and diagnostics never appear here.
