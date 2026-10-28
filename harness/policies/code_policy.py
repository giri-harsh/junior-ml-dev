"""AST code policy: a defence-in-depth check run before any agent code reaches a sandbox.

It is NOT sufficient alone (dynamic tricks can evade static checks); isolation is the real
boundary. The policy removes the obvious abuses and gives a clear, auditable refusal reason.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

BANNED_MODULES = {
    "socket", "subprocess", "requests", "urllib", "urllib3", "http", "httpx", "ftplib",
    "smtplib", "telnetlib", "ctypes", "importlib", "pty", "multiprocessing", "asyncio.subprocess",
}  # fmt: skip
BANNED_CALLS = {"eval", "exec", "compile", "__import__", "breakpoint", "input"}
BANNED_DOTTED_CALLS = {"os.system", "os.popen", "os.exec", "os.spawn", "os.fork", "os.kill"}
BANNED_ATTRS = {
    "__subclasses__", "__globals__", "__builtins__", "__mro__", "__bases__", "__code__",
}  # fmt: skip
HIDDEN_NAME = re.compile(r"scorer|test_labels|hidden|\.\./|/etc/|/proc/|\.ssh|\.env", re.IGNORECASE)
WORKSPACE = "/workspace"


@dataclass(frozen=True)
class Violation:
    rule: str
    line: int
    detail: str


@dataclass(frozen=True)
class PolicyResult:
    allowed: bool
    violations: list[Violation]


def _dotted(node: ast.AST) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


class _Visitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[Violation] = []
        self.aliases: dict[str, str] = {}  # local name -> real dotted name

    def add(self, rule: str, node: ast.AST, detail: str) -> None:
        self.violations.append(Violation(rule, getattr(node, "lineno", 0), detail))

    def _check_module(self, name: str, node: ast.AST) -> None:
        root = name.split(".")[0]
        if name in BANNED_MODULES or root in BANNED_MODULES:
            self.add("banned_import", node, name)

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            self._check_module(a.name, node)
            self.aliases[a.asname or a.name.split(".")[0]] = a.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        self._check_module(mod, node)
        for a in node.names:
            self._check_module(f"{mod}.{a.name}", node)
            self.aliases[a.asname or a.name] = f"{mod}.{a.name}"
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in BANNED_ATTRS:
            self.add("banned_attribute", node, node.attr)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in {"__builtins__", "__loader__", "__spec__"}:
            self.add("banned_name", node, node.id)

    def visit_Call(self, node: ast.Call) -> None:
        name = _dotted(node.func)
        if name:
            head, _, rest = name.partition(".")
            real = self.aliases.get(head, head) + ("." + rest if rest else "")
            if real in BANNED_CALLS or name in BANNED_CALLS:
                self.add("banned_call", node, real)
            if any(real == d or real.startswith(d) for d in BANNED_DOTTED_CALLS):
                self.add("banned_call", node, real)
            if real in {"getattr", "setattr", "delattr"} and len(node.args) >= 2:
                arg = node.args[1]
                risky = BANNED_ATTRS | {"system", "popen", "__import__"}
                if isinstance(arg, ast.Constant) and arg.value in risky:
                    self.add("banned_call", node, f"{real}(..., {arg.value!r})")
            if real in {"open", "io.open"}:
                self._check_open(node)
            if real.rsplit(".", 1)[-1] in {"read_csv", "read_parquet", "read_json", "read_pickle"}:
                self._check_path_constants(node)
        self.generic_visit(node)

    def _check_path_constants(self, node: ast.Call) -> None:
        for arg in [*node.args, *(k.value for k in node.keywords)]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                self._check_path(arg.value, node)

    def _check_path(self, path: str, node: ast.AST) -> None:
        if HIDDEN_NAME.search(path):
            self.add("hidden_path", node, path)
        elif path.startswith("/") and not path.startswith(WORKSPACE):
            self.add("path_outside_workspace", node, path)

    def _check_open(self, node: ast.Call) -> None:
        if not node.args:
            self.add("open_without_path", node, "open()")
            return
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            self._check_path(first.value, node)
        else:
            self.add("dynamic_open_path", node, "open() path must be a string literal")


def check_code(code: str) -> PolicyResult:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return PolicyResult(False, [Violation("syntax_error", exc.lineno or 0, exc.msg)])
    v = _Visitor()
    v.visit(tree)
    return PolicyResult(not v.violations, v.violations)
