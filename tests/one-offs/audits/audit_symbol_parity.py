"""Structural symbol-parity audit: v0.3.6 log-command.py vs Phase 0b cclogger/.

Walks the AST of the original (pulled from git) and the new tree (log-command.py
+ all cclogger/*.py), collects top-level functions, classes (with methods),
dataclass fields, and module-level constants. Reports any symbol present in
the original but missing or signature-mutated in the new layout.

This complements diff_check.py (behavioral byte-identical) and pytest (covers
specific touched symbols) by proving every v0.3.6 symbol made it through the
modularization unchanged in shape.

Usage:
  python tests/one-offs/thinking/audit_symbol_parity.py
  python tests/one-offs/thinking/audit_symbol_parity.py --base-ref v0.3.6
  python tests/one-offs/thinking/audit_symbol_parity.py --verbose

Exit codes:
  0 = full parity (every original symbol present with matching signature)
  1 = parity drift detected (symbols missing or signatures changed)
  2 = audit failed (git ref unavailable, AST parse error, etc.)
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
HOOKS_SCRIPTS = REPO_ROOT / "hooks" / "scripts"
CCLOGGER_DIR = HOOKS_SCRIPTS / "cclogger"


@dataclass
class FunctionSig:
    name: str
    args: list[str]              # positional + kwonly arg names in order
    defaults: list[str]          # default values (as ast.unparse strings)
    kwonly_defaults: dict[str, str]
    decorators: list[str]
    is_async: bool = False

    def signature_str(self) -> str:
        parts = list(self.args)
        # Append defaults in human-readable form
        if self.defaults:
            n = len(self.defaults)
            for i, d in enumerate(self.defaults):
                idx = len(self.args) - n + i
                if 0 <= idx < len(parts):
                    parts[idx] = f"{parts[idx]}={d}"
        deco = "".join(f"@{d} " for d in self.decorators)
        async_ = "async " if self.is_async else ""
        return f"{deco}{async_}def {self.name}({', '.join(parts)})"


@dataclass
class ClassSig:
    name: str
    bases: list[str]
    decorators: list[str]
    methods: dict[str, FunctionSig] = field(default_factory=dict)
    fields: list[str] = field(default_factory=list)  # dataclass field names

    def signature_str(self) -> str:
        deco = "".join(f"@{d} " for d in self.decorators)
        bases = f"({', '.join(self.bases)})" if self.bases else ""
        return f"{deco}class {self.name}{bases}"


@dataclass
class ModuleSymbols:
    functions: dict[str, FunctionSig] = field(default_factory=dict)
    classes: dict[str, ClassSig] = field(default_factory=dict)
    constants: dict[str, str] = field(default_factory=dict)  # name -> value repr

    def all_names(self) -> set[str]:
        return set(self.functions) | set(self.classes) | set(self.constants)


# ---------------------------------------------------------------------------
# AST extraction
# ---------------------------------------------------------------------------

def _arg_name(arg: ast.arg) -> str:
    return arg.arg


def _func_sig(node: ast.FunctionDef | ast.AsyncFunctionDef) -> FunctionSig:
    args = node.args
    pos_names = [_arg_name(a) for a in args.posonlyargs] + [_arg_name(a) for a in args.args]
    kwonly_names = [_arg_name(a) for a in args.kwonlyargs]
    all_args = pos_names + (["*"] if args.kwonlyargs else []) + kwonly_names
    if args.vararg:
        all_args.insert(len(pos_names), f"*{args.vararg.arg}")
    if args.kwarg:
        all_args.append(f"**{args.kwarg.arg}")

    defaults = [ast.unparse(d) for d in args.defaults]
    kwonly_defaults = {}
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        if default is not None:
            kwonly_defaults[arg.arg] = ast.unparse(default)

    decorators = [ast.unparse(d) for d in node.decorator_list]
    return FunctionSig(
        name=node.name,
        args=all_args,
        defaults=defaults,
        kwonly_defaults=kwonly_defaults,
        decorators=decorators,
        is_async=isinstance(node, ast.AsyncFunctionDef),
    )


def _class_sig(node: ast.ClassDef) -> ClassSig:
    bases = [ast.unparse(b) for b in node.bases]
    decorators = [ast.unparse(d) for d in node.decorator_list]
    cls = ClassSig(name=node.name, bases=bases, decorators=decorators)

    is_dataclass = any("dataclass" in d for d in decorators)

    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cls.methods[child.name] = _func_sig(child)
        elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            # Dataclass field
            if is_dataclass:
                cls.fields.append(child.target.id)
        elif isinstance(child, ast.Assign):
            # Class-level constant (e.g., FILE_PREFIX = "")
            for target in child.targets:
                if isinstance(target, ast.Name):
                    cls.fields.append(target.id)
    return cls


def _is_constant_name(name: str) -> bool:
    """Heuristic: ALL_CAPS or single-underscore + caps means module constant."""
    return name.isupper() or (name.startswith("_") and name[1:].isupper())


def extract_symbols(source: str) -> ModuleSymbols:
    """Parse a Python source string and extract its top-level public surface."""
    tree = ast.parse(source)
    syms = ModuleSymbols()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            syms.functions[node.name] = _func_sig(node)
        elif isinstance(node, ast.ClassDef):
            syms.classes[node.name] = _class_sig(node)
        elif isinstance(node, ast.Assign):
            # Module-level constant assignment (e.g., DEBUG_LOG = ...)
            for target in node.targets:
                if isinstance(target, ast.Name) and _is_constant_name(target.id):
                    syms.constants[target.id] = ast.unparse(node.value)
        elif isinstance(node, ast.AnnAssign):
            # Annotated module-level assignment (e.g., TOOL_CATEGORIES: dict[..] = {..})
            if isinstance(node.target, ast.Name) and _is_constant_name(node.target.id):
                if node.value is not None:
                    syms.constants[node.target.id] = ast.unparse(node.value)

    return syms


# ---------------------------------------------------------------------------
# Source loaders
# ---------------------------------------------------------------------------

def load_original_from_git(ref: str) -> str:
    """Load the v0.3.6 log-command.py from git.

    Reads as bytes + decodes UTF-8 explicitly because git's stdout on Windows
    is otherwise interpreted as cp1252 by Python, which fails on the box-drawing
    chars used in the SESSION_MARKER constants.
    """
    try:
        result = subprocess.run(
            ["git", "show", f"{ref}:hooks/scripts/log-command.py"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        )
        return result.stdout.decode("utf-8")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else "(no stderr)"
        print(f"ERROR: git show {ref}:hooks/scripts/log-command.py failed:\n{stderr}",
              file=sys.stderr)
        sys.exit(2)


def load_new_tree() -> ModuleSymbols:
    """Union all symbols across log-command.py + cclogger/*.py.

    Excludes cclogger/__init__.py from the union (it is a re-export shim;
    its symbols are duplicates of home-module symbols). However, we DO use
    __init__.py to detect whether a symbol is re-exported into the package
    namespace, which matters for backward-compat tests.
    """
    union = ModuleSymbols()

    # log-command.py itself
    log_command = HOOKS_SCRIPTS / "log-command.py"
    if log_command.exists():
        syms = extract_symbols(log_command.read_text(encoding="utf-8"))
        union.functions.update(syms.functions)
        union.classes.update(syms.classes)
        union.constants.update(syms.constants)

    # cclogger/*.py (excluding __init__.py to avoid double-counting re-exports)
    for module_path in sorted(CCLOGGER_DIR.glob("*.py")):
        if module_path.name == "__init__.py":
            continue
        syms = extract_symbols(module_path.read_text(encoding="utf-8"))
        # On collision, prefer the one that actually defines (later module
        # wins; for our case there should be no collisions across
        # cclogger/ since extraction was strictly partitioned).
        for name, fn in syms.functions.items():
            if name in union.functions:
                print(f"  WARN: function '{name}' defined in multiple modules", file=sys.stderr)
            union.functions[name] = fn
        for name, cls in syms.classes.items():
            if name in union.classes:
                print(f"  WARN: class '{name}' defined in multiple modules", file=sys.stderr)
            union.classes[name] = cls
        for name, val in syms.constants.items():
            if name in union.constants:
                print(f"  WARN: constant '{name}' defined in multiple modules", file=sys.stderr)
            union.constants[name] = val

    return union


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

def compare_function(orig: FunctionSig, new: FunctionSig) -> list[str]:
    """Return a list of diffs (empty = identical for our purposes)."""
    diffs = []
    if orig.args != new.args:
        diffs.append(f"args: {orig.args} -> {new.args}")
    if orig.defaults != new.defaults:
        diffs.append(f"defaults: {orig.defaults} -> {new.defaults}")
    if orig.kwonly_defaults != new.kwonly_defaults:
        diffs.append(f"kwonly_defaults: {orig.kwonly_defaults} -> {new.kwonly_defaults}")
    # Decorator differences are noisy (e.g., @dataclass vs @dataclass()) — only
    # flag if a major decorator (classmethod/staticmethod/property) is added/removed
    important_deco = {"classmethod", "staticmethod", "property"}
    orig_imp = {d for d in orig.decorators if d in important_deco}
    new_imp = {d for d in new.decorators if d in important_deco}
    if orig_imp != new_imp:
        diffs.append(f"decorators: {orig_imp} -> {new_imp}")
    return diffs


def compare_class(orig: ClassSig, new: ClassSig) -> list[str]:
    diffs = []
    if orig.bases != new.bases:
        diffs.append(f"bases: {orig.bases} -> {new.bases}")
    # Compare method sets
    orig_methods = set(orig.methods)
    new_methods = set(new.methods)
    missing = orig_methods - new_methods
    if missing:
        diffs.append(f"missing methods: {sorted(missing)}")
    # Compare each method signature
    for mname in sorted(orig_methods & new_methods):
        m_diffs = compare_function(orig.methods[mname], new.methods[mname])
        if m_diffs:
            diffs.append(f"method '{mname}': {'; '.join(m_diffs)}")
    # Compare dataclass fields
    if set(orig.fields) != set(new.fields):
        missing_fields = set(orig.fields) - set(new.fields)
        added_fields = set(new.fields) - set(orig.fields)
        if missing_fields:
            diffs.append(f"missing fields: {sorted(missing_fields)}")
        if added_fields:
            diffs.append(f"added fields: {sorted(added_fields)}")
    return diffs


def audit(orig: ModuleSymbols, new: ModuleSymbols, verbose: bool = False) -> int:
    """Compare original vs new symbol surfaces. Returns issue count."""
    issues = 0

    # Functions
    print("\n=== Top-level functions ===")
    orig_funcs = set(orig.functions)
    new_funcs = set(new.functions)
    missing = orig_funcs - new_funcs
    for name in sorted(missing):
        print(f"  MISSING: function '{name}'")
        issues += 1
    matched = sorted(orig_funcs & new_funcs)
    for name in matched:
        diffs = compare_function(orig.functions[name], new.functions[name])
        if diffs:
            print(f"  CHANGED: function '{name}': {'; '.join(diffs)}")
            issues += 1
        elif verbose:
            print(f"  OK:      {name}")
    if not missing and not any(compare_function(orig.functions[n], new.functions[n])
                                 for n in matched):
        print(f"  All {len(orig_funcs)} top-level functions match")

    # Classes
    print("\n=== Top-level classes ===")
    orig_classes = set(orig.classes)
    new_classes = set(new.classes)
    missing = orig_classes - new_classes
    for name in sorted(missing):
        print(f"  MISSING: class '{name}'")
        issues += 1
    for name in sorted(orig_classes & new_classes):
        diffs = compare_class(orig.classes[name], new.classes[name])
        if diffs:
            print(f"  CHANGED: class '{name}':")
            for d in diffs:
                print(f"             {d}")
            issues += 1
        elif verbose:
            print(f"  OK:      {name}")
    if not missing and not any(compare_class(orig.classes[n], new.classes[n])
                                  for n in (orig_classes & new_classes)):
        print(f"  All {len(orig_classes)} top-level classes match")

    # Constants
    print("\n=== Module-level constants ===")
    orig_consts = set(orig.constants)
    new_consts = set(new.constants)
    missing = orig_consts - new_consts
    for name in sorted(missing):
        print(f"  MISSING: constant '{name}'")
        issues += 1
    for name in sorted(orig_consts & new_consts):
        if orig.constants[name] != new.constants[name]:
            print(f"  CHANGED: constant '{name}':")
            print(f"             orig: {orig.constants[name][:80]}")
            print(f"             new:  {new.constants[name][:80]}")
            issues += 1
        elif verbose:
            print(f"  OK:      {name}")
    if not missing:
        unchanged = sum(1 for n in (orig_consts & new_consts)
                          if orig.constants[n] == new.constants[n])
        print(f"  {unchanged}/{len(orig_consts)} constants identical")

    # Newly-added (informational)
    new_only_funcs = sorted(new_funcs - orig_funcs)
    new_only_classes = sorted(new_classes - orig_classes)
    if new_only_funcs or new_only_classes:
        print("\n=== Net-new symbols (not in v0.3.6) ===")
        for n in new_only_funcs:
            print(f"  + function '{n}'")
        for n in new_only_classes:
            print(f"  + class '{n}'")

    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                       formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-ref", default="v0.3.6",
                          help="Git ref for the baseline log-command.py (default: v0.3.6)")
    parser.add_argument("--verbose", "-v", action="store_true",
                          help="Print every matching symbol, not just the diffs")
    args = parser.parse_args()

    print(f"Auditing symbol parity: {args.base_ref} log-command.py vs current cclogger/ tree\n")

    print(f"Loading original from git ({args.base_ref})...")
    orig_source = load_original_from_git(args.base_ref)
    orig_syms = extract_symbols(orig_source)
    print(f"  {len(orig_syms.functions)} functions, "
          f"{len(orig_syms.classes)} classes, "
          f"{len(orig_syms.constants)} constants")

    print("\nLoading new tree (log-command.py + cclogger/*.py)...")
    new_syms = load_new_tree()
    print(f"  {len(new_syms.functions)} functions, "
          f"{len(new_syms.classes)} classes, "
          f"{len(new_syms.constants)} constants")

    issues = audit(orig_syms, new_syms, verbose=args.verbose)

    print(f"\n{'=' * 70}")
    if issues == 0:
        print(f"PARITY OK: every v0.3.6 symbol present with matching signature")
        sys.exit(0)
    else:
        print(f"DRIFT DETECTED: {issues} symbol(s) missing or changed")
        sys.exit(1)


if __name__ == "__main__":
    main()
