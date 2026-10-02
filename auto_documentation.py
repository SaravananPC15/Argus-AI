"""
auto_documentation.py — Protocol Auto-Documentation (Self-Writing Comments).

Parses a Python file with the ast module, finds every function/method
missing a docstring, asks the LLM for a concise one, and splices it in
by line number — never a full-file LLM rewrite, which risks silently
corrupting code the LLM "helpfully" changes. Writes the result to a new
file (never overwrites the original in place), so there's always an
un-touched copy to diff against.
"""

import ast
import os
import ollama
import model_router


def _generate_docstring(func_source: str, func_name: str) -> str:
    prompt = f"""
    Write a single concise docstring (1-3 lines, Google-style, no decorative
    formatting) for this Python function. Output ONLY the docstring text,
    without the triple quotes and without repeating the function code.

    def {func_name}(...):
        {func_source[:600]}
    """
    try:
        response = ollama.chat(
            model=model_router.select_model("auto_documentation"),
            messages=[{'role': 'system', 'content': prompt}]
        )
        text = response['message']['content'].strip()
        # Strip accidental triple-quotes or markdown fences the model might add
        text = text.strip('`').strip('"').strip("'").strip()
        return text
    except Exception as e:
        print(f"[Auto-Documentation Error] {func_name}: {e}")
        return f"{func_name} — TODO: describe what this function does."


def document_file(filepath: str) -> str:
    """Entry point for executor.py's 'auto_documentation' action.
    Returns a spoken-style summary and writes <name>_documented.py."""
    if not os.path.exists(filepath):
        return f"I can't find {filepath} to document."

    with open(filepath, "r", encoding="utf-8") as f:
        source_lines = f.readlines()
    source_text = "".join(source_lines)

    try:
        tree = ast.parse(source_text, filename=filepath)
    except SyntaxError as e:
        return f"{filepath} has a syntax error at line {e.lineno}, so I can't safely parse it to add docstrings."

    # Collect (insertion_line, indent, docstring) for every function/method
    # missing a docstring, walking bottom-up so earlier insertions don't
    # shift the line numbers of ones we haven't processed yet.
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            has_docstring = (
                node.body and isinstance(node.body[0], ast.Expr) and
                isinstance(getattr(node.body[0], "value", None), (ast.Constant,)) and
                isinstance(node.body[0].value.value, str)
            )
            if has_docstring:
                continue
            func_source = ast.get_source_segment(source_text, node) or ""
            insertion_line = node.body[0].lineno - 1 if node.body else node.lineno  # 0-indexed line to insert before
            indent = " " * (node.col_offset + 4)
            targets.append((insertion_line, indent, node.name, func_source))

    if not targets:
        return f"{filepath} already has docstrings on every function — nothing to add, macha."

    targets.sort(key=lambda t: t[0], reverse=True)  # bottom-up insertion

    print(f"[Auto-Documentation] Drafting docstrings for {len(targets)} functions...")
    new_lines = list(source_lines)
    for insertion_line, indent, func_name, func_source in targets:
        docstring_text = _generate_docstring(func_source, func_name)
        docstring_block = f'{indent}"""{docstring_text}"""\n'
        new_lines.insert(insertion_line, docstring_block)

    base, ext = os.path.splitext(filepath)
    output_path = f"{base}_documented{ext}"
    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    return f"Documented {len(targets)} functions in {filepath}, macha. Saved the annotated version to {output_path} — didn't touch your original."
