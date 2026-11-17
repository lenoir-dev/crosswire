import argparse
import sys
from importlib.resources import files
from . import __version__, git, report, combined_report
from .combined import analyze_combined
from .planner import plan
from . import plan_report
from .engine import analyze


class Parser(argparse.ArgumentParser):
    def error(self, message):
        """Error."""
        self.exit(2, f'crosswire: error: {message}\n')


def _main(argv=None):
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
    check.add_argument('--repo')
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
    plan_parser.add_argument('--repo')
    plan_parser.add_argument('--target', required=True)
    plan_parser.add_argument('--src', action='append')
    plan_parser.add_argument('--format', choices=('text', 'json'), default='text')
    plan_parser.add_argument('--no-cache', action='store_true')
    plan_parser.add_argument('branches', nargs='+', metavar='BRANCH')
    schema_parser = sub.add_parser('schema', help='Print an offline JSON Schema')
    schema_parser.add_argument('--version', choices=('1', '2'), required=True)
    schema_parser.add_argument('--mode', choices=('check', 'plan'), default='check')
    args = parser.parse_args(argv)
    if args.command == 'schema':
        if args.mode == 'plan' and args.version != '2':
            parser.error('plan schema requires version 2')
        name = f'plan-v{args.version}.schema.json' if args.mode == 'plan' else f'report-v{args.version}.schema.json'
        print(files('crosswire').joinpath('schemas', name).read_text(encoding='utf-8'), end='')
        return 0
    if args.command == 'plan':
        try:
            result = plan(args.repo or '.', args.branches, args.target, args.src, not args.no_cache,
                          repro_repo=args.repo)
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
            result = analyze_combined(args.repo or '.', args.branches, args.target,
                                      args.src, cache=not args.no_cache, repro_repo=args.repo)
            formatter = combined_report
        else:
            result = analyze(args.repo or '.', args.branches, args.base, args.src,
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


def main(argv=None):
    """Run the CLI; unexpected failures are operational errors, never conflicts."""
    try:
        return _main(argv)
    except Exception as exc:
        print(f'crosswire: error: internal error: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2
