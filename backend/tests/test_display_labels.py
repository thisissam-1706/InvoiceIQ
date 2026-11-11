"""Every finding code raised by the pipeline must have a user-facing display name."""
import importlib.util
from pathlib import Path

from app.pipeline import CODE_LABELS, DISPLAY_LABELS, code_info, code_title

ROOT = Path(__file__).resolve().parents[2]


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_codes_doc", ROOT / "backend" / "scripts" / "gen_codes_doc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load_generator()


def test_every_code_used_in_pipeline_has_display_label():
    used = set(gen.collect_codes())
    assert len(used) > 30  # guards against the AST scan silently finding nothing
    missing = sorted(used - set(DISPLAY_LABELS))
    assert not missing, f"Add these codes to DISPLAY_LABELS in backend/app/pipeline/__init__.py: {missing}"


def test_display_labels_are_well_formed_and_not_stale():
    for code, entry in DISPLAY_LABELS.items():
        assert entry["title"] and entry["description"], code
        assert len(entry["title"]) <= 35, f"{code}: title too long"
        assert "_" not in entry["title"], code
    assert set(CODE_LABELS) <= set(DISPLAY_LABELS)
    assert not sorted(set(DISPLAY_LABELS) - set(gen.collect_codes())), "DISPLAY_LABELS has codes no check uses"


def test_unknown_code_falls_back_to_humanised_text():
    assert code_title("SOME_NEW_CODE") == "Some new code"
    assert code_info("SOME_NEW_CODE") == {"title": "Some new code", "description": ""}


def test_codes_md_is_up_to_date():
    assert (ROOT / "CODES.md").read_text() == gen.render(), "Run: python backend/scripts/gen_codes_doc.py"
