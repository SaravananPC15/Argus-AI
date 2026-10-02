"""
complexity_auditor.py — Protocol Big-O Complexity Auditor.

Parses a Python file with `ast` and estimates each function's time
complexity from syntactic patterns: loop nesting depth (the primary,
most reliable signal), recursive self-calls (and whether more than one
happens per invocation, the classic naive-Fibonacci shape), and a few
"hidden cost" patterns that quietly turn an apparent O(n) loop into
something worse -- `x in a_list` inside a loop (O(n) per check unless
it's actually a set/dict, which static analysis alone can't always
tell) and `sort()`/`sorted()` calls inside a loop.

BE HONEST ABOUT WHAT THIS IS: determining a program's exact asymptotic
complexity in general is undecidable (it reduces to the halting
problem for pathological cases) -- no static analyzer, this one
included, can give you a guaranteed-correct answer for arbitrary code.
This gives you a heuristic ESTIMATE plus the actual reasoning behind
it (which loops are nested inside which, at what depth, which calls
look recursive) so you can sanity-check the estimate yourself rather
than trust a black-box label. It doesn't account for early returns/
breaks that change the practical runtime, input-dependent branching,
or amortized cost (e.g. a dict insert is O(1) amortized, not "a hidden
loop" even though CPython implements it with one internally).
"""

import ast


_SORT_CALL_NAMES = {"sort", "sorted"}
_MEMOIZATION_HINTS = {"lru_cache", "cache", "cached_property", "memoize"}


class _FunctionComplexityVisitor(ast.NodeVisitor):
    """Walks a single function's body. Instantiate one per function so
    loop-depth and recursion tracking don't leak across functions."""

    def __init__(self, function_name: str):
        self.function_name = function_name
        self.max_loop_depth = 0
        self._current_depth = 0
        self.findings = []          # [{"lineno", "kind", "detail"}]
        self.recursive_call_sites = 0

    def _loop(self, node, label: str):
        self._current_depth += 1
        self.max_loop_depth = max(self.max_loop_depth, self._current_depth)
        if self._current_depth >= 2:
            self.findings.append({
                "lineno": node.lineno,
                "kind": "nested_loop",
                "detail": f"{label} nested at depth {self._current_depth} -- "
                          f"each level multiplies the cost of everything inside it.",
            })
        self.generic_visit(node)
        self._current_depth -= 1

    def visit_For(self, node):
        self._loop(node, "for loop")

    def visit_While(self, node):
        self._loop(node, "while loop")

    def visit_ListComp(self, node):
        # A comprehension with more than one `for` clause is itself a
        # nested loop, even though it's one Python statement.
        extra_depth = len(node.generators) - 1
        self._current_depth += 1 + max(extra_depth, 0)
        self.max_loop_depth = max(self.max_loop_depth, self._current_depth)
        if self._current_depth >= 2:
            self.findings.append({
                "lineno": node.lineno,
                "kind": "nested_comprehension",
                "detail": f"comprehension with {len(node.generators)} 'for' clause(s) "
                          f"reaches nesting depth {self._current_depth}.",
            })
        self.generic_visit(node)
        self._current_depth -= 1 + max(extra_depth, 0)

    visit_SetComp = visit_DictComp = visit_GeneratorExp = visit_ListComp

    def visit_Call(self, node):
        func = node.func
        name = getattr(func, "attr", None) or getattr(func, "id", None)

        if isinstance(func, ast.Name) and func.id == self.function_name:
            self.recursive_call_sites += 1

        if self._current_depth >= 1 and name in _SORT_CALL_NAMES:
            self.findings.append({
                "lineno": node.lineno,
                "kind": "sort_in_loop",
                "detail": f"'{name}()' called inside a loop -- sorting is O(m log m) "
                          f"EACH time this line runs, not free; if this can be hoisted "
                          f"outside the loop (sort once, not per-iteration), do that.",
            })

        self.generic_visit(node)

    def visit_Compare(self, node):
        if self._current_depth >= 1:
            for op, comparator in zip(node.ops, node.comparators):
                if isinstance(op, (ast.In, ast.NotIn)):
                    hint = _guess_container_kind(comparator)
                    self.findings.append({
                        "lineno": node.lineno,
                        "kind": "membership_in_loop",
                        "detail": (f"'in' check inside a loop against "
                                   f"'{hint}' -- if that's a list or tuple, each check "
                                   f"is O(m), turning an apparently-O(n) loop into "
                                   f"O(n*m); a set or dict would make this O(1)."),
                    })
        self.generic_visit(node)


def _guess_container_kind(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, (ast.List, ast.Tuple)):
        return "a literal list/tuple written inline"
    if isinstance(node, ast.Set):
        return "a literal set (this one's fine -- O(1) membership)"
    return ast.dump(node)[:40]


def _has_memoization_decorator(node: ast.FunctionDef) -> bool:
    for dec in node.decorator_list:
        dec_name = getattr(dec, "id", None) or getattr(dec, "attr", None) or getattr(
            getattr(dec, "func", None), "id", None)
        if dec_name in _MEMOIZATION_HINTS:
            return True
    return False


def _label_for_depth(depth: int) -> str:
    return {0: "O(1)", 1: "O(n)", 2: "O(n^2)", 3: "O(n^3)"}.get(depth, f"O(n^{depth})")


def audit_source(source: str, filename: str = "<source>") -> list:
    """
    Returns a list of per-function reports:
      {
        "function": str, "lineno": int,
        "estimated_complexity": str,          # e.g. "O(n^2)"
        "max_loop_nesting_depth": int,
        "is_recursive": bool,
        "recursive_call_sites": int,          # >1 without memoization is the naive-Fibonacci shape
        "likely_exponential_recursion": bool,
        "findings": [...],
      }
    Raises SyntaxError if `source` isn't valid Python (callers should
    catch this -- it just means "can't audit this file", not a bug).
    """
    tree = ast.parse(source, filename=filename)
    reports = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        visitor = _FunctionComplexityVisitor(node.name)
        for stmt in node.body:
            visitor.visit(stmt)

        is_recursive = visitor.recursive_call_sites > 0
        memoized = _has_memoization_decorator(node)
        likely_exponential = is_recursive and visitor.recursive_call_sites > 1 and not memoized

        complexity = _label_for_depth(visitor.max_loop_depth)
        depth_suffix = " per loop level" if visitor.max_loop_depth > 0 else ""
        if likely_exponential:
            complexity += f"{depth_suffix}, plus likely-exponential recursion (see below)"
        elif is_recursive and not memoized:
            complexity += f"{depth_suffix}, plus recursion (depends on recursion depth/branching)"
        elif is_recursive and memoized:
            complexity += f"{depth_suffix}; recursion is memoized, so repeated subproblems are cheap"

        reports.append({
            "function": node.name,
            "lineno": node.lineno,
            "estimated_complexity": complexity,
            "max_loop_nesting_depth": visitor.max_loop_depth,
            "is_recursive": is_recursive,
            "recursive_call_sites": visitor.recursive_call_sites,
            "likely_exponential_recursion": likely_exponential,
            "findings": visitor.findings,
        })

    return reports


def format_report(reports: list) -> str:
    if not reports:
        return "No functions found to audit."
    lines = []
    for r in reports:
        lines.append(f"def {r['function']}()  (line {r['lineno']})")
        lines.append(f"  Estimated: {r['estimated_complexity']}  "
                      f"[loop nesting depth: {r['max_loop_nesting_depth']}]")
        if r["likely_exponential_recursion"]:
            lines.append(f"  ⚠ {r['recursive_call_sites']} recursive call site(s) per invocation, "
                          f"no memoization decorator found -- classic naive-recursion blowup "
                          f"pattern (e.g. naive Fibonacci). Consider @functools.lru_cache or an "
                          f"explicit memo dict if subproblems repeat.")
        for f in r["findings"]:
            lines.append(f"  - line {f['lineno']}: {f['detail']}")
        lines.append("")
    lines.append("Heuristic static analysis based on syntactic nesting -- not a proof. "
                  "Doesn't account for early exits, input-dependent branching, or amortized cost.")
    return "\n".join(lines)


if __name__ == "__main__":
    sample = '''
def linear_scan(items, target):
    for item in items:
        if item == target:
            return True
    return False

def bubble_sort(items):
    for i in range(len(items)):
        for j in range(len(items) - 1):
            if items[j] > items[j+1]:
                items[j], items[j+1] = items[j+1], items[j]

def hidden_quadratic(names, allowed_list):
    for name in names:
        if name in allowed_list:   # allowed_list is a list -> O(m) each time
            print(name)

def naive_fib(n):
    if n <= 1:
        return n
    return naive_fib(n - 1) + naive_fib(n - 2)

import functools
@functools.lru_cache
def memoized_fib(n):
    if n <= 1:
        return n
    return memoized_fib(n - 1) + memoized_fib(n - 2)

def sorts_every_iteration(rows):
    for row in rows:
        row.sort()
'''
    reports = audit_source(sample)
    print(format_report(reports))
