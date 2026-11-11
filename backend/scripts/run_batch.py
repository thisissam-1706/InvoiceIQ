"""Reset runtime data, process every sample in filename order and compare with EXPECTED."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["offline", "groq", "gemini", "openai"], help="override LLM_PROVIDER for this batch")
    args = parser.parse_args()
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider

    from backend.app import db
    from backend.app.llm import build_client
    from backend.app.models import Run
    from backend.app.pipeline.orchestrator import create_run, process_run
    from backend.app.settings import SAMPLES_DIR
    from backend.scripts.generate_samples import EXPECTED
    from backend.scripts.generate_samples import main as generate

    if not all((SAMPLES_DIR / name).exists() for name in EXPECTED):
        generate()
    db.init_db()
    if not db.reference_is_seeded():
        db.reseed_reference()
    db.reset_runtime_data()

    resolved = build_client()
    print(f"Provider: {resolved.client.provider} / {resolved.client.model}")
    if resolved.note:
        print(f"Note: {resolved.note}")
    print()

    rows, failures = [], 0
    for name in sorted(EXPECTED):
        run = create_run(SAMPLES_DIR / name, name, "batch")
        actual = process_run(run.id, stage_delay_ms=0, resolved=resolved) or "FAILED"
        with db.session() as s:
            done = s.get(Run, run.id)
        findings = json.loads(done.rules_json or "{}").get("findings", [])
        codes = sorted({f["code"] for f in findings})
        expected = EXPECTED[name]
        ok = actual == expected["decision"] and set(expected["codes"]) <= set(codes)
        failures += not ok
        rows.append((name, expected["decision"], actual, "✓" if ok else "✗", ", ".join(codes) or "—", done.error_message))

    width = max(len(r[0]) for r in rows)
    print(f"{'file':<{width}}  {'expected':<8}  {'actual':<8}  ok  reason codes")
    print("-" * (width + 60))
    for name, exp, act, ok, codes, err in rows:
        print(f"{name:<{width}}  {exp:<8}  {act:<8}  {ok}   {codes}")
        if err:
            print(f"{'':<{width}}  error: {err}")
    print()
    print(f"{len(rows) - failures}/{len(rows)} samples match the expected decision and primary reason codes")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
