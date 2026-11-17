import argparse
import sys
from . import __version__, git, report, combined_report
from .combined import analyze_combined
from .planner import plan
from . import plan_report
from .engine import analyze


class Parser(argparse.ArgumentParser):
    def error(self, message):
        """Error."""
        self.exit(2, f'crosswire: error: {message}\n')


def main(argv=None):
    """Main."""
    parser = Parser(
        prog='crosswire',
        description='Detect semantic conflicts between Git branches.')
    parser.add_argument(
        '--version',
        action='version',
        version=f'crosswire {__version__}')
    sub = parser.add_subparsers(
        dest='command',
        required=True,
        parser_class=Parser)
    check = sub.add_parser('check', help='Check every pair of branches')
    check.add_argument('--repo', default='.')
    base_group = check.add_mutually_exclusive_group()
    base_group.add_argument('--base')
    base_group.add_argument('--target')
    check.add_argument('--src', action='append')
    check.add_argument(
        '--format',
        choices=(
            'text',
            'json',
            'github',
            'sarif'),
        default='text')
    check.add_argument('--no-textual', action='store_true')
    check.add_argument('--no-cache', action='store_true')
    check.add_argument('--combined', action='store_true')
    check.add_argument('branches', nargs='+', metavar='BRANCH')
    plan_parser = sub.add_parser('plan', help='Find a safe merge order')
    plan_parser.add_argument('--repo', default='.')
    plan_parser.add_argument('--target', required=True)
    plan_parser.add_argument('--src', action='append')
    plan_parser.add_argument('--format', choices=('text', 'json'), default='text')
    plan_parser.add_argument('--no-cache', action='store_true')
    plan_parser.add_argument('branches', nargs='+', metavar='BRANCH')
    args = parser.parse_args(argv)
    if args.command == 'plan':
        try:
            result = plan(args.repo, args.branches, args.target, args.src, not args.no_cache)
        except git.GitError as exc:
            print(f'crosswire: error: {exc}', file=sys.stderr)
            return 2
        rendered = plan_report.json_report(result) if args.format == 'json' else plan_report.text(result, args.target)
        print(rendered)
        return 1 if result['blocked'] else 0
    if args.combined and not args.target:
        parser.error('--combined requires --target')
    if args.combined and args.no_textual:
        parser.error('--combined is incompatible with --no-textual')
    try:
        if args.combined:
            result = analyze_combined(args.repo, args.branches, args.target,
                                      args.src, cache=not args.no_cache)
            formatter = combined_report
        else:
            result = analyze(args.repo, args.branches, args.base, args.src,
                             not args.no_textual, target=args.target,
                             cache=not args.no_cache)
            formatter = report
    except git.GitError as exc:
        print(f'crosswire: error: {exc}', file=sys.stderr)
        return 2
    rendered = {'text': formatter.text, 'json': formatter.json_report,
                'github': formatter.github, 'sarif': formatter.sarif}[args.format](result)
    if rendered:
        print(rendered)
    return 1 if any(f.severity == 'error' for f in result.findings) else 0
