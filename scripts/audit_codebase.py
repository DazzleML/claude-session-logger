#!/usr/bin/env python3
"""
Codebase Audit Tool

Compare functions between different git commits to track code evolution,
identify missing functionality, and generate diff reports.

Usage:
    python scripts/audit_codebase.py [baseline_commit] [current_commit]
    python scripts/audit_codebase.py --help

Examples:
    # Compare against v0.1.0 baseline
    python scripts/audit_codebase.py c4528d8

    # Compare two specific commits
    python scripts/audit_codebase.py c4528d8 HEAD

    # Generate full report with diffs
    python scripts/audit_codebase.py c4528d8 --full-diff
"""

import subprocess
import re
import sys
import io
import argparse
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import difflib


class CodebaseAuditor:
    """Audit tool for comparing codebases across git commits."""

    def __init__(self, repo_path: str = '.'):
        self.repo_path = Path(repo_path).absolute()
        # Set UTF-8 encoding for output
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    def get_python_files(self, commit: str) -> List[str]:
        """Get list of Python files in a commit."""
        result = subprocess.run(
            ['git', 'ls-tree', commit, '--name-only', '-r'],
            capture_output=True, text=True, cwd=self.repo_path
        )

        if result.returncode != 0:
            print(f"Error: Could not list files in commit {commit}")
            return []

        return [f for f in result.stdout.strip().split('\n') if f.endswith('.py')]

    def extract_functions(self, commit: str, file_path: str) -> Dict[str, Dict]:
        """Extract all functions from a file in a specific commit."""
        result = subprocess.run(
            ['git', 'show', f'{commit}:{file_path}'],
            capture_output=True, text=True, cwd=self.repo_path
        )

        if result.returncode != 0:
            return {}

        functions = {}
        lines = result.stdout.split('\n')

        for i, line in enumerate(lines, 1):
            match = re.match(r'^(\s*)def\s+([a-zA-Z_][a-zA-Z0-9_]*)', line)
            if match:
                indent = len(match.group(1))
                func_name = match.group(2)
                functions[func_name] = {
                    'line': i,
                    'indent': indent,
                    'code': self._extract_function_code(lines, i-1, indent)
                }

        return functions

    def _extract_function_code(self, lines: List[str], start_idx: int, base_indent: int) -> str:
        """Extract complete function code from lines."""
        func_lines = [lines[start_idx]]

        for i in range(start_idx + 1, len(lines)):
            line = lines[i]

            # Check for end of function
            if line.strip():
                current_indent = len(line) - len(line.lstrip())
                if current_indent <= base_indent:
                    if line.strip().startswith(('def ', 'class ', '@')):
                        break

            func_lines.append(line)

            # Stop at empty line after dedent
            if not line.strip() and i > start_idx + 1:
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if next_line.strip():
                        next_indent = len(next_line) - len(next_line.lstrip())
                        if next_indent <= base_indent:
                            break

        return '\n'.join(func_lines).rstrip()

    def find_function_in_commit(self, commit: str, func_name: str) -> List[str]:
        """Find all locations of a function in a commit."""
        result = subprocess.run(
            ['git', 'grep', '-l', f'def {func_name}', commit],
            capture_output=True, text=True, cwd=self.repo_path
        )

        if result.returncode == 0:
            # Remove commit prefix from paths
            return [path.split(':', 1)[1] for path in result.stdout.strip().split('\n') if path]
        return []

    def generate_function_diff(self, func1: Optional[str], func2: Optional[str],
                             func_name: str) -> str:
        """Generate unified diff between two function implementations."""
        if func1 is None:
            func1 = "# Function not found\n"
        if func2 is None:
            func2 = "# Function not found\n"

        lines1 = func1.splitlines(keepends=True)
        lines2 = func2.splitlines(keepends=True)

        diff = difflib.unified_diff(
            lines1, lines2,
            fromfile=f'baseline/{func_name}',
            tofile=f'current/{func_name}',
            lineterm=''
        )

        return ''.join(diff)

    def audit_commits(self, baseline_commit: str, current_commit: str = 'HEAD',
                     full_diff: bool = False, output_format: str = 'markdown') -> Dict:
        """Perform complete audit between two commits."""
        print(f"# Codebase Audit Report\n")
        print(f"**Baseline**: {baseline_commit}")
        print(f"**Current**: {current_commit}")
        print(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        # Get all Python files from both commits
        baseline_files = set(self.get_python_files(baseline_commit))
        current_files = set(self.get_python_files(current_commit))

        # Track all functions
        all_functions = {}
        missing_functions = []
        moved_functions = []
        changed_functions = []
        new_functions = []

        # Analyze baseline functions
        for file_path in baseline_files:
            functions = self.extract_functions(baseline_commit, file_path)
            for func_name, func_data in functions.items():
                all_functions[f"{file_path}::{func_name}"] = {
                    'baseline_file': file_path,
                    'baseline_line': func_data['line'],
                    'baseline_code': func_data['code'],
                    'current_locations': [],
                    'status': 'unknown'
                }

        # Find functions in current commit
        for key, data in all_functions.items():
            file_path, func_name = key.split('::')

            # Check original location
            if file_path in current_files:
                current_funcs = self.extract_functions(current_commit, file_path)
                if func_name in current_funcs:
                    data['current_locations'].append(file_path)
                    data['current_code'] = current_funcs[func_name]['code']
                    data['status'] = 'same' if data['baseline_code'] == data['current_code'] else 'modified'

            # Search other locations if not found
            if not data['current_locations']:
                locations = self.find_function_in_commit(current_commit, func_name)
                if locations:
                    data['current_locations'] = locations
                    data['status'] = 'moved'
                    # Get code from first location
                    funcs = self.extract_functions(current_commit, locations[0])
                    if func_name in funcs:
                        data['current_code'] = funcs[func_name]['code']
                else:
                    data['status'] = 'missing'
                    missing_functions.append(key)

        # Generate report
        if output_format == 'markdown':
            self._generate_markdown_report(all_functions, full_diff)
        elif output_format == 'json':
            return self._generate_json_report(all_functions)

        return all_functions

    def _generate_markdown_report(self, functions: Dict, full_diff: bool = False):
        """Generate markdown format report."""
        # Summary statistics
        total = len(functions)
        missing = sum(1 for f in functions.values() if f['status'] == 'missing')
        moved = sum(1 for f in functions.values() if f['status'] == 'moved')
        modified = sum(1 for f in functions.values() if f['status'] == 'modified')
        unchanged = sum(1 for f in functions.values() if f['status'] == 'same')

        print("## Summary\n")
        print(f"- **Total Functions**: {total}")
        print(f"- **Unchanged**: {unchanged} ({unchanged/total*100:.1f}%)")
        print(f"- **Modified**: {modified} ({modified/total*100:.1f}%)")
        print(f"- **Moved**: {moved} ({moved/total*100:.1f}%)")
        print(f"- **Missing**: {missing} ({missing/total*100:.1f}%)\n")

        # Missing functions
        if missing > 0:
            print("## Missing Functions\n")
            print("| Function | Original Location | Line |")
            print("|----------|------------------|------|")
            for key, data in functions.items():
                if data['status'] == 'missing':
                    file_path, func_name = key.split('::')
                    print(f"| `{func_name}` | {file_path} | {data['baseline_line']} |")
            print()

        # Moved functions
        if moved > 0:
            print("## Moved Functions\n")
            print("| Function | Original Location | New Location(s) |")
            print("|----------|------------------|-----------------|")
            for key, data in functions.items():
                if data['status'] == 'moved':
                    file_path, func_name = key.split('::')
                    new_locs = ', '.join(data['current_locations'])
                    print(f"| `{func_name}` | {file_path} | {new_locs} |")
            print()

        # Modified functions with diffs
        if full_diff and modified > 0:
            print("## Modified Functions\n")
            for key, data in functions.items():
                if data['status'] == 'modified':
                    file_path, func_name = key.split('::')
                    print(f"### {file_path}::{func_name}\n")
                    diff = self.generate_function_diff(
                        data.get('baseline_code'),
                        data.get('current_code'),
                        func_name
                    )
                    if diff:
                        print("```diff")
                        print(diff)
                        print("```\n")

    def _generate_json_report(self, functions: Dict) -> Dict:
        """Generate JSON format report."""
        return {
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total': len(functions),
                'missing': sum(1 for f in functions.values() if f['status'] == 'missing'),
                'moved': sum(1 for f in functions.values() if f['status'] == 'moved'),
                'modified': sum(1 for f in functions.values() if f['status'] == 'modified'),
                'unchanged': sum(1 for f in functions.values() if f['status'] == 'same'),
            },
            'functions': functions
        }


def main():
    parser = argparse.ArgumentParser(
        description='Audit codebase changes between git commits',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('baseline', help='Baseline commit hash or tag')
    parser.add_argument('current', nargs='?', default='HEAD',
                       help='Current commit to compare (default: HEAD)')
    parser.add_argument('--full-diff', action='store_true',
                       help='Include full diffs for modified functions')
    parser.add_argument('--output', choices=['markdown', 'json'], default='markdown',
                       help='Output format (default: markdown)')
    parser.add_argument('--output-file', help='Save output to file')
    parser.add_argument('--focus-files', nargs='+',
                       help='Only analyze specific files or patterns')

    args = parser.parse_args()

    auditor = CodebaseAuditor()

    # Redirect output if file specified
    if args.output_file:
        output_file = Path(args.output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = open(output_file, 'w', encoding='utf-8')

    try:
        result = auditor.audit_commits(
            args.baseline,
            args.current,
            args.full_diff,
            args.output
        )

        if args.output == 'json' and not args.output_file:
            print(json.dumps(result, indent=2))

    finally:
        if args.output_file:
            sys.stdout.close()
            # Reset stdout and print to stderr
            sys.stdout = sys.__stdout__
            print(f"Report saved to: {args.output_file}", file=sys.stderr)


if __name__ == '__main__':
    main()