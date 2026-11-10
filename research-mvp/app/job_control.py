"""Owner-scoped job controls and safe, append-only execution events."""

from sqlalchemy import select
from .db import Job, Audit, audit, now

TERMINAL = {"done", "done_with_warnings", "failed", "cancelled", "cancel_unknown"}
CANCEL_STATES = {"cancel_requested", "cancelling", "cancelled"}


class Cancelled(Exception):
    pass


class LostLease(Exception):
    pass


class InvalidProviderResult(ValueError):
    pass


def event(db, job, code, message, **details):
    audit(db, job.review_id, "worker", "job_event", {"job_id": job.id, "event": code, "message": message, **details})


def checkpoint(db, job, lock=False):
    with db.no_autoflush:
        q = select(Job.status, Job.payload).where(Job.id == job.id)
        if lock:
            q = q.with_for_update()
        row = db.execute(q).one()
    if row.status in CANCEL_STATES:
        raise Cancelled()
    token = job.payload.get("lease_token")
    if token and row.payload.get("lease_token") != token:
        raise LostLease()
    return row.payload


def poll_events(db, job, raw):
    status = raw.get("status", "unknown")
    previous = job.payload.get("provider_status")
    job.payload = {**job.payload, "provider_status": status, "provider_checked_at": now(), "provider_cost_usd": raw.get("totalCostUsd")}
    if status != previous:
        event(db, job, "provider_status", "Estado confirmado no Browser Use: " + status, provider_status=status)


def public_logs(db, job):
    events = []
    for a in db.scalars(select(Audit).where(Audit.review_id == job.review_id).order_by(Audit.created_at)):
        p = a.payload
        if p.get("job_id") != job.id:
            continue
        if a.action == "job_event":
            events.append(
                {
                    "at": a.created_at,
                    "event": p.get("event"),
                    "message": p.get("message"),
                    "details": {k: v for k, v in p.items() if k not in ("job_id", "event", "message")},
                }
            )
        elif a.action in ("job_error", "job_retry", "job_cancel_requested", "job_cancelled"):
            events.append(
                {
                    "at": a.created_at,
                    "event": a.action,
                    "message": {
                        "job_error": "Falha registrada: " + p.get("type", "erro"),
                        "job_retry": "Reprocessamento solicitado",
                        "job_cancel_requested": "Cancelamento solicitado",
                        "job_cancelled": "Cancelamento confirmado",
                    }[a.action],
                    "details": {k: v for k, v in p.items() if k != "job_id"},
                }
            )
    return {
        "job_id": job.id,
        "kind": job.kind,
        "status": job.status,
        "created_at": job.created_at,
        "attempts": job.attempts,
        "run_id": job.external_id,
        "provider_status": job.payload.get("provider_status"),
        "provider_checked_at": job.payload.get("provider_checked_at"),
        "last_activity_at": job.payload.get("last_activity_at"),
        "next_check_at": job.available_at if job.status == "pending" else None,
        "progress": job.payload.get("progress", {}),
        "validation": job.payload.get("validation", {}),
        "error": job.error,
        "events": events[-250:],
    }
