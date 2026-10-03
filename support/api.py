from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from support.actions import approve_ticket
from support.metrics import metrics
from support.pipeline import process
from support.store import ConflictError, Store
from support.ui_api import router as ui_router

app = FastAPI(title="Matiks Support · dry-run")

app.include_router(ui_router)


class Approval(BaseModel):
    reviewer: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=0)
    handling_seconds: float | None = Field(default=None, ge=0)


@app.get("/health")
def health():
    Store()
    return {"status": "ok", "mode": "dry_run", "external_dispatch": False}


@app.get("/tickets")
def tickets():
    return [t.model_dump() for t in Store().tickets()]


@app.get("/metrics")
def dashboard_metrics():
    return metrics(Store())


@app.get("/tickets/{ticket_id}/evidence")
def evidence(ticket_id: str):
    store = Store()
    try:
        ticket = store.get(ticket_id)
    except KeyError:
        raise HTTPException(404, "Ticket not found") from None
    return [e.model_dump() for e in store.evidence_for(ticket_id, ticket.active_run)]


@app.post("/tickets/{ticket_id}/process")
async def investigate(ticket_id: str):
    try:
        return (await process(Store(), ticket_id)).model_dump()
    except KeyError:
        raise HTTPException(404, "Ticket not found") from None
    except ConflictError as error:
        raise HTTPException(409, str(error)) from None


@app.post("/tickets/{ticket_id}/approve")
def approve(ticket_id: str, request: Approval):
    try:
        store = Store()
        approve_ticket(
            store, ticket_id, request.reviewer, request.revision, request.handling_seconds
        )
        return store.get(ticket_id).model_dump()
    except KeyError:
        raise HTTPException(404, "Ticket not found") from None
    except ConflictError as error:
        raise HTTPException(409, str(error)) from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
