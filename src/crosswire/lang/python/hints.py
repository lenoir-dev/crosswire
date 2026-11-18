"""Python advice, preserving the released reason and remediation text."""

import re

def hint(finding):
    """Give actionable advice only where the finding provides evidence."""
    rule = finding.rule
    symbol = finding.symbol
    culprits = getattr(finding, 'culprits', ()) or ()
    other = getattr(finding, 'other_branch', None)
    resolved = getattr(finding, 'resolved_by', None)
    if rule in ('CW001', 'CW002') and resolved:
        return f"merge {', '.join(resolved)} first"
    if rule == 'CW001':
        renamed = re.search(r'\(renamed to `([^`]+)`\?\)', finding.message)
        if renamed:
            return f'use `{renamed.group(1)}`'
        if symbol:
            return f'restore or re-export `{symbol}`'
    if rule == 'CW003':
        return 'keep one definition'
    if rule == 'CW004' and 'Alembic' in finding.message:
        return 'add a merge revision'
    if rule == 'CW005':
        causes = culprits or ((other,) if other else ())
        if causes:
            return f"rebase {finding.branch} onto {', '.join(causes)}"
    if rule == 'CW006' and culprits:
        return f"merge {', '.join(culprits)} together with a compatibility shim"
    return None

