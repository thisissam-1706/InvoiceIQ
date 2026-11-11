"""Collect every finding code used in the pipeline and (re)generate CODES.md.

Codes, severities and stages are read from the actual ctx.add(...) / ctx.passed(...) calls in
backend/app/pipeline/*.py, so the table cannot drift from the code.

    python backend/scripts/gen_codes_doc.py          # rewrite CODES.md
    python backend/scripts/gen_codes_doc.py --check  # exit 1 if CODES.md is out of date
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE_DIR = ROOT / "backend" / "app" / "pipeline"
sys.path.insert(0, str(ROOT / "backend"))

from app.pipeline import DISPLAY_LABELS, STAGES  # noqa: E402

SEVERITY_ORDER = ["block", "review", "warning", "info", "pass"]
EFFECT = {
    "block": "REJECT",
    "review": "HOLD",
    "warning": "None (shown only)",
    "info": "None (shown only)",
    "pass": "None (check passed)",
}


def collect_codes() -> dict[str, dict]:
    """code -> {"stage": str, "severities": set[str], "critical": bool} from ctx.add / ctx.passed calls."""
    found: dict[str, dict] = {}
    for path in sorted(PIPELINE_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("add", "passed")
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "ctx"
            ):
                continue
            if not (node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                raise ValueError(f"{path.name}:{node.lineno}: ctx.{node.func.attr} code must be a string literal")
            code = node.args[0].value
            if node.func.attr == "passed":
                severity = "pass"
            else:
                arg = node.args[1] if len(node.args) > 1 else None
                if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                    raise ValueError(f"{path.name}:{node.lineno}: severity of {code} must be a string literal")
                severity = arg.value
            critical = any(k.arg == "critical" and getattr(k.value, "value", False) is True for k in node.keywords)
            entry = found.setdefault(code, {"stage": path.stem, "severities": set(), "critical": False})
            entry["severities"].add(severity)
            entry["critical"] = entry["critical"] or critical
    return found


def _sev(entry: dict) -> str:
    return " / ".join(s for s in SEVERITY_ORDER if s in entry["severities"])


def _effect(entry: dict) -> str:
    effects = {EFFECT[s] for s in entry["severities"]}
    return " / ".join(sorted(effects))


def render() -> str:
    codes = collect_codes()
    out = [
        "# Finding codes",
        "",
        "Every check in the pipeline reports a **finding code**. The app shows the *Display name* below; the raw code",
        "appears only as small grey text on the Run Detail page, for debugging.",
        "",
        "This file is generated from the `ctx.add(...)` / `ctx.passed(...)` calls and from `DISPLAY_LABELS` in",
        "`backend/app/pipeline/__init__.py`. Regenerate it with `python backend/scripts/gen_codes_doc.py`.",
        "",
        "**Effect on decision:** any `block` finding gives **REJECT**; otherwise any `review` finding gives **HOLD**;",
        "otherwise **APPROVE**. `warning` and `info` findings are shown but do not change the decision by themselves",
        "(an admin can still list any code under *Never auto-approve* in Settings to force HOLD). `pass` means the check succeeded.",
        "",
    ]
    for stage in STAGES:
        rows = [(c, e) for c, e in codes.items() if e["stage"] == stage]
        if not rows:
            continue
        rows.sort(key=lambda r: (min(SEVERITY_ORDER.index(s) for s in r[1]["severities"]), r[0]))
        out += [f"## {stage}", "", "| Code | Display name | What it means | Severity | Pipeline stage | Effect on decision (APPROVE/HOLD/REJECT) |", "|---|---|---|---|---|---|"]
        for code, e in rows:
            label = DISPLAY_LABELS[code]
            sev = _sev(e) + (" (critical)" if e["critical"] else "")
            out.append(f"| `{code}` | {label['title']} | {label['description']} | {sev} | {stage} | {_effect(e)} |")
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    target = ROOT / "CODES.md"
    text = render()
    if "--check" in sys.argv:
        sys.exit(0 if target.exists() and target.read_text() == text else 1)
    target.write_text(text)
    print(f"wrote {target} ({len(collect_codes())} codes)")
