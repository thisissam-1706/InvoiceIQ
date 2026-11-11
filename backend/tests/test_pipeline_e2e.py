import json

import pytest
from sqlmodel import select

from backend.app import db
from backend.app.llm import ResolvedClient
from backend.app.llm.offline import OfflineClient
from backend.app.models import POConsumption, Run, RunStep
from backend.app.pipeline import STAGES, ingest
from backend.app.pipeline.orchestrator import create_run, process_run
from backend.app.settings import SAMPLES_DIR
from backend.scripts.generate_samples import EXPECTED
from backend.scripts.generate_samples import main as generate_samples


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    if not all((SAMPLES_DIR / name).exists() for name in EXPECTED):
        generate_samples()
    return SAMPLES_DIR


@pytest.fixture
def results(fresh_db, samples, tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "UPLOADS_DIR", tmp_path / "uploads")
    resolved = ResolvedClient(OfflineClient())
    out = {}
    for name in sorted(EXPECTED):
        run = create_run(samples / name, name, "batch")
        process_run(run.id, stage_delay_ms=0, resolved=resolved)
        with db.session() as s:
            out[name] = s.get(Run, run.id)
    return out


def test_every_sample_gets_expected_decision(results):
    mismatches = []
    for name, expected in EXPECTED.items():
        run = results[name]
        found = {f["code"] for f in json.loads(run.rules_json)["findings"]}
        if run.decision != expected["decision"] or not set(expected["codes"]) <= found:
            mismatches.append((name, expected, run.decision, sorted(found), run.error_message))
    assert not mismatches, mismatches


def test_all_stages_recorded_in_order(results):
    run = results["01_acme_clean.pdf"]
    with db.session() as s:
        steps = s.exec(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.id)).all()
    assert [st.stage for st in steps] == STAGES
    assert all(st.status == "completed" and st.summary for st in steps)


def test_only_approved_invoices_consume_po_budget(results):
    with db.session() as s:
        rows = s.exec(select(POConsumption)).all()
    consumed = {(r.po_number, r.amount) for r in rows}
    approved = {n for n, r in results.items() if r.decision == "APPROVE"}
    assert approved == {n for n, e in EXPECTED.items() if e["decision"] == "APPROVE"}
    assert ("PO-2026-0102", "6000.00") in consumed and ("PO-2026-0102", "5500.00") in consumed
    assert len(rows) == len(approved)


def test_non_pdf_fails_cleanly(fresh_db, tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "UPLOADS_DIR", tmp_path / "uploads")
    bogus = tmp_path / "notes.pdf"
    bogus.write_text("this is not a pdf")
    run = create_run(bogus, "notes.pdf", "upload")
    assert process_run(run.id, stage_delay_ms=0, resolved=ResolvedClient(OfflineClient())) is None
    with db.session() as s:
        failed = s.get(Run, run.id)
    assert failed.status == "failed" and failed.decision is None
    assert "not a PDF" in failed.error_message
