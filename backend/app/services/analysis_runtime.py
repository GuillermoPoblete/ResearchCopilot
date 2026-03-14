import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pandas as pd
from openai import OpenAI

ALLOWED_IMPORTS = {
    "math",
    "statistics",
    "numpy",
    "pandas",
    "matplotlib",
    "matplotlib.pyplot",
}

RESULT_TEMPLATE = {
    "summary": "",
    "metrics": {},
    "tables": [],
    "charts": [],
    "diagnostics": [],
}

RESULT_BLOCK_RE = re.compile(
    r"__RESULT_START__\s*(\{.*?\})\s*__RESULT_END__", re.DOTALL
)


def _validate_generated_code(code: str) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"Generated code has syntax errors: {exc}") from exc

    banned_calls = {"exec", "eval", "open", "__import__", "compile", "input"}
    banned_modules = {
        "os",
        "sys",
        "subprocess",
        "socket",
        "pathlib",
        "shutil",
        "requests",
        "httpx",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
                if mod in banned_modules:
                    raise ValueError(f"Import not allowed: {mod}")
                if mod not in ALLOWED_IMPORTS:
                    raise ValueError(f"Import not allowed: {mod}")

        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in banned_modules:
                raise ValueError(f"Import not allowed: {mod}")
            if mod not in ALLOWED_IMPORTS:
                raise ValueError(f"Import not allowed: {mod}")

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in banned_calls:
                raise ValueError(f"Call not allowed: {node.func.id}")


def generate_analysis_code(user_prompt: str, context: dict) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    client = OpenAI(api_key=api_key)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a Python data analyst. "
                "Write ONLY executable Python code, no markdown fences. "
                "Assume `df` is a pandas DataFrame with the target data. "
                "Use only pandas, numpy, math, statistics, matplotlib.pyplot. "
                "Never read files, never call network, never use subprocess/os/sys/pathlib."
            ),
        },
        {
            "role": "user",
            "content": (
                "User request:\n"
                f"{user_prompt}\n\n"
                "Data context (JSON):\n"
                f"{json.dumps(context, ensure_ascii=True)}\n\n"
                "You must assign a dict variable called `result` with keys:\n"
                "- summary (string)\n"
                "- metrics (dict)\n"
                "- tables (list of {name, columns, rows})\n"
                "- charts (list of {name, mime_type, data_base64})\n"
                "- diagnostics (list of strings)\n"
                "If no chart is needed, return charts=[]."
            ),
        },
    ]

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.1,
    )
    code = (completion.choices[0].message.content or "").strip()
    if code.startswith("```"):
        code = code.strip("`")
        code = code.replace("python", "", 1).strip()

    _validate_generated_code(code)
    return code


def _runtime_wrapper_code(user_code: str) -> str:
    prefix = [
        "import base64",
        "import io",
        "import json",
        "import traceback",
        "",
        "import matplotlib.pyplot as plt",
        "import numpy as np",
        "import pandas as pd",
        "",
        'with open("payload.json", "r", encoding="utf-8") as f:',
        "    payload = json.load(f)",
        "",
        'df = pd.DataFrame(payload["df"]["data"], columns=payload["df"]["columns"])',
        'context = payload["context"]',
        "",
        "def dataframe_to_table(name, frame, max_rows=200):",
        "    trimmed = frame.head(max_rows).astype(object).where(pd.notnull(frame.head(max_rows)), None)",
        "    return {",
        '        "name": str(name),',
        '        "columns": [str(c) for c in trimmed.columns.tolist()],',
        '        "rows": trimmed.values.tolist(),',
        "    }",
        "",
        "def fig_to_base64(fig):",
        "    buf = io.BytesIO()",
        '    fig.savefig(buf, format="png", bbox_inches="tight")',
        "    buf.seek(0)",
        '    return base64.b64encode(buf.read()).decode("ascii")',
        "",
        "def to_jsonable(value):",
        "    if isinstance(value, dict):",
        "        return {str(k): to_jsonable(v) for k, v in value.items()}",
        "    if isinstance(value, (list, tuple, set)):",
        "        return [to_jsonable(v) for v in value]",
        "    if isinstance(value, pd.DataFrame):",
        "        return dataframe_to_table('dataframe', value)",
        "    if isinstance(value, pd.Series):",
        "        series = value.astype(object).where(pd.notnull(value), None)",
        "        return series.tolist()",
        "    if isinstance(value, np.generic):",
        "        return value.item()",
        "    if isinstance(value, pd.Timestamp):",
        "        return value.isoformat()",
        "    if value is None:",
        "        return None",
        "    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):",
        "        return None",
        "    return value",
        "",
        f"result = {json.dumps(RESULT_TEMPLATE, ensure_ascii=True)}",
        "",
        "try:",
    ]
    suffix = [
        "except Exception as exc:",
        '    result["diagnostics"].append(f"Execution error: {type(exc).__name__}: {exc}")',
        "    traceback.print_exc()",
        "",
        "if not isinstance(result, dict):",
        '    raise ValueError("`result` must be a dictionary")',
        'for k in ("summary", "metrics", "tables", "charts", "diagnostics"):',
        "    if k not in result:",
        '        raise ValueError(f"Missing result key: {k}")',
        "",
        "result = to_jsonable(result)",
        "",
        'print("__RESULT_START__")',
        "print(json.dumps(result, ensure_ascii=True))",
        'print("__RESULT_END__")',
    ]
    return "\n".join(prefix + textwrap.indent(user_code.strip(), "    ").splitlines() + suffix)


def execute_analysis_code(
    *,
    code: str,
    dataframe: pd.DataFrame,
    context: dict,
    timeout_sec: int = 30,
) -> dict:
    payload = {
        "df": dataframe.astype(object).where(pd.notnull(dataframe), None).to_dict(orient="split"),
        "context": context,
    }

    with tempfile.TemporaryDirectory(prefix="analysis_run_") as tmp:
        tmp_path = Path(tmp)
        script_path = tmp_path / "runner.py"
        payload_path = tmp_path / "payload.json"
        script_path.write_text(_runtime_wrapper_code(code), encoding="utf-8")
        payload_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")

        try:
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(tmp_path),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "status": "error",
                "error": f"Execution timed out after {timeout_sec}s",
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
                "result": RESULT_TEMPLATE,
            }

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    match = RESULT_BLOCK_RE.search(stdout)
    if not match:
        return {
            "status": "error",
            "error": "Executor did not return a valid result payload",
            "stdout": stdout,
            "stderr": stderr,
            "result": RESULT_TEMPLATE,
        }

    try:
        result = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {
            "status": "error",
            "error": "Executor returned invalid JSON payload",
            "stdout": stdout,
            "stderr": stderr,
            "result": RESULT_TEMPLATE,
        }

    status = "ok" if proc.returncode == 0 else "error"
    error = None if status == "ok" else f"Python process exited with code {proc.returncode}"
    return {
        "status": status,
        "error": error,
        "stdout": stdout,
        "stderr": stderr,
        "result": result,
    }
