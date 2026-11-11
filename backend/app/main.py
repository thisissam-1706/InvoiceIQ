import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import select

from . import db
from .api import reference, runs, system
from .inbox_watcher import watcher
from .models import Run
from .pipeline.orchestrator import audit, worker
from .settings import FRONTEND_DIST

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def recover_interrupted_runs() -> None:
    """Runs live in an in-memory queue, so a restart loses them; re-queue or fail them explicitly."""
    with db.session() as s:
        pending = s.exec(select(Run).where(Run.status.in_(["queued", "running"])).order_by(Run.created_at)).all()
        for run in pending:
            if run.status == "running":
                run.status = "failed"
                run.error_message = "The server restarted while this run was processing. Use Re-run to process it again."
                s.add(run)
            else:
                worker.enqueue(run.id)
        s.commit()
    for run in pending:
        if run.status == "failed":
            audit(run.id, "run_failed", "Interrupted by server restart")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    if not db.reference_is_seeded():
        db.reseed_reference()
    worker.start()
    recover_interrupted_runs()
    watcher.start()
    yield
    watcher.stop()


app = FastAPI(title="InvoiceIQ", version="1.0", lifespan=lifespan)
app.include_router(runs.router)
app.include_router(reference.router)
app.include_router(system.router)

if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, "Not found")
    candidate = (FRONTEND_DIST / full_path).resolve()
    if full_path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
        return FileResponse(candidate)
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return HTMLResponse(
        "<h1>InvoiceIQ API is running</h1><p>The web UI has not been built yet. Run <code>./setup.sh</code> "
        "or <code>cd frontend && npm install && npm run build</code>. API docs: <a href='/docs'>/docs</a></p>"
    )
