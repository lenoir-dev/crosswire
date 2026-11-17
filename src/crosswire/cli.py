import argparse
import sys
from . import __version__, git, report
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
    check.add_argument('branches', nargs='+', metavar='BRANCH')
    args = parser.parse_args(argv)
    try:
        result = analyze(
            args.repo,
            args.branches,
            args.base,
            args.src,
            not args.no_textual,
            target=args.target,
            cache=not args.no_cache)
    except git.GitError as exc:
        print(f'crosswire: error: {exc}', file=sys.stderr)
        return 2
    rendered = {
        'text': report.text,
        'json': report.json_report,
        'github': report.github,
        'sarif': report.sarif}[
        args.format](result)
    if rendered:
        print(rendered)
    return 1 if any(f.severity == 'error' for f in result.findings) else 0
