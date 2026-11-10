import json, logging, time, uuid
from .job_control import checkpoint, event, poll_events, Cancelled, LostLease, InvalidProviderResult
from .config import settings
from sqlalchemy import select, update, or_, and_, text
from .db import Session, Job, Search, Article, Record, Review, audit, now, enqueue
from . import pubmed, browser, files

log = logging.getLogger("fullmark.worker")


class Later(Exception):
    def __init__(self, seconds):
        self.seconds = seconds


def ingest(db, job):
    search = db.get(Search, job.payload["search_id"])

    def progress(value):
        checkpoint(db, job)
        with Session() as monitor:
            current = monitor.get(Job, job.id)
            current.payload = {**current.payload, "last_activity_at": now(), "progress": {**value, "updated_at": now()}}
            monitor.commit()

    event(db, job, "pubmed_search", "Consulta enviada ao PubMed")
    # Preserve the exact query and frozen filter snapshot before receiving provider results.
    context = dict(search.raw or {})
    records, raw = pubmed.search(
        search.query, search.max_records, progress=progress, sort=context.get("filters", {}).get("sort", "pub date")
    )
    raw["fullmark"] = context
    raw["executed_at"] = now()
    search.raw = raw
    search.total_found = int(raw["esearchresult"]["count"])
    search.translated_query = raw["esearchresult"].get("querytranslation", "")
    new_count = 0
    duplicate_count = 0
    for metadata in records:
        key = pubmed.identity(metadata)
        # PMID fallback also merges an identifier-enriched record already imported.
        article = db.scalar(select(Article).where(Article.review_id == job.review_id, Article.identity == key))
        if not article:
            for candidate in db.scalars(select(Article).where(Article.review_id == job.review_id)):
                if metadata.get("pmid") and candidate.metadata_json.get("pmid") == metadata["pmid"]:
                    article = candidate
                    break
        if not article:
            article = Article(review_id=job.review_id, identity=key, metadata_json=metadata)
            db.add(article)
            db.flush()
            new_count += 1
        else:
            duplicate_count += 1
        exists = db.scalar(select(Record.id).where(Record.search_id == search.id, Record.source_id == metadata["pmid"]))
        if not exists:
            db.add(Record(review_id=job.review_id, search_id=search.id, article_id=article.id, source_id=metadata["pmid"], raw=metadata))
    search.raw = {**raw, "stats": {"imported": len(records), "new": new_count, "duplicates": duplicate_count}}
    if context.get("automatic_screening") and records:
        r = db.scalar(select(Review).where(Review.id == job.review_id).with_for_update())
        active = db.scalar(
            select(Job.id).where(
                Job.review_id == job.review_id, Job.kind == "browser", Job.status.in_(["pending", "running", "needs_reconciliation"])
            )
        )
        if not active:
            enqueue(db, job.review_id, "browser", "auto-" + search.id, {})
    audit(
        db,
        job.review_id,
        "worker",
        "pubmed_import",
        {
            "search_id": search.id,
            "retrieved": len(records),
            "total_found": search.total_found,
            "truncated": search.total_found > len(records),
        },
    )


def reserve_provider(db, job):
    # Runs keep executing while their local poll jobs are pending. Limit remote
    # concurrency independently of the two local worker threads.
    if db.bind.dialect.name == "postgresql":
        if not db.scalar(text("select pg_try_advisory_xact_lock(73941028)")):
            raise Later(5)
    from sqlalchemy import func

    active = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(
            Job.id != job.id,
            Job.kind.in_(["browser", "planning"]),
            Job.status.in_(["pending", "running", "cancel_requested", "cancelling", "needs_reconciliation", "cancel_unknown"]),
            Job.payload["submission_started"].as_boolean() == True,
        )
    )
    if active >= 2:
        raise Later(5)


def browse(db, job):
    r = db.get(Review, job.review_id)
    checkpoint(db, job)
    if not job.external_id:
        r = db.scalar(select(Review).where(Review.id == job.review_id).with_for_update())
        if db.scalar(
            select(Job.id).where(
                Job.review_id == job.review_id,
                Job.kind == "browser",
                Job.id != job.id,
                or_(Job.external_id.is_not(None), Job.status == "running", Job.payload["submission_started"].as_boolean() == True),
                Job.status.in_(["pending", "running", "needs_reconciliation"]),
            )
        ):
            raise Later(5)
        if job.payload.get("submission_started"):
            job.status = "needs_reconciliation"
            job.error = "Submission outcome unknown; reconcile Browser Use dashboard before resubmitting"
            return
        articles = list(db.scalars(select(Article).where(Article.review_id == r.id)))
        if job.request_key.startswith("auto-"):
            articles = [a for a in articles if not a.recommendation]
            if not articles:
                return
        if not articles:
            raise ValueError("Import PubMed records before browser research")
        reserve_provider(db, job)
        # Durable marker before the non-idempotent provider request prevents blind paid resubmission.
        # Separate large reviews into bounded, resumable provider batches.
        articles = articles[:50]
        job.payload = {**job.payload, "submission_started": True, "submitted_at": now(), "article_ids": [a.id for a in articles]}
        event(db, job, "provider_submit", "Enviando lote para análise", article_count=len(articles))
        checkpoint(db, job, lock=True)
        db.commit()
        data = [
            {
                "article_id": a.id,
                "title": a.metadata_json.get("title"),
                "abstract": a.metadata_json.get("abstract"),
                "pmid": a.metadata_json.get("pmid"),
                "url": a.metadata_json.get("url"),
            }
            for a in articles
        ]
        job.external_id = browser.submit(r.protocol, data)
        db.commit()
        raise Later(5)
    result = browser.poll(job.external_id, observer=lambda raw: poll_events(db, job, raw))
    if result is None:
        if now() - job.payload.get("submitted_at", job.created_at) > 3600:
            raise ValueError("Browser run still active after one hour; inspect provider dashboard")
        raise Later(5)
    output, raw = result
    r = db.scalar(select(Review).where(Review.id == job.review_id).with_for_update())
    checkpoint(db, job)
    allowed = set(job.payload["article_ids"])
    grouped = {}
    unknown = 0
    invalid = set(raw.get("_invalid_finding_ids", []))
    for finding in output.findings:
        if finding.article_id not in allowed:
            unknown += 1
            continue
        grouped.setdefault(finding.article_id, []).append(finding)
    counts = {
        "expected": len(allowed),
        "verified": 0,
        "manual_review": 0,
        "unknown_ids": unknown,
        "retained_previous": 0,
        "rejected_incoming": 0,
    }
    for aid in sorted(allowed):
        a = db.get(Article, aid)
        if not a or a.review_id != job.review_id:
            raise InvalidProviderResult("Artigo não pertence à pesquisa")
        evidence = a.metadata_json.get("title", "") + "\n" + a.metadata_json.get("abstract", "")
        matches = grouped.get(aid, [])
        reason_code = None
        f = matches[0] if len(matches) == 1 else None
        if aid in invalid:
            reason_code = "invalid_item"
        elif not matches:
            reason_code = "missing_item"
        elif len(matches) > 1:
            reason_code = "duplicate_id"
        elif f.quote and f.quote not in evidence:
            reason_code = "non_literal_quote"
        elif not f.quote:
            reason_code = "missing_evidence"
        if reason_code:
            counts["rejected_incoming"] += 1
            previous = a.recommendation
            if previous.get("quote") and previous["quote"] in evidence and previous.get("recommendation") in ("include", "exclude"):
                counts["retained_previous"] += 1
                counts["verified"] += 1
                continue
            counts["manual_review"] += 1
            a.recommendation = {
                "article_id": aid,
                "recommendation": "uncertain",
                "reason": "A resposta automática deste artigo precisa de revisão: a evidência não foi validada. Leia o título e o resumo antes de decidir.",
                "quote": "",
                "priority": 0,
                "evidence_status": "manual_review_required",
                "validation_issue": reason_code,
                "run_id": job.external_id,
                "prompt_version": "1.1",
                "model": raw.get("model"),
                "at": now(),
            }
        else:
            counts["verified"] += 1
            a.recommendation = {
                **f.model_dump(),
                "evidence_status": "verified",
                "run_id": job.external_id,
                "prompt_version": "1.1",
                "model": raw.get("model"),
                "at": now(),
            }
    job.payload = {**job.payload, "validation": counts, "provider_status": "completed", "last_activity_at": now()}
    if counts["rejected_incoming"] or unknown:
        job.status = "done_with_warnings"
    event(db, job, "validation_complete", "Análise conferida por artigo; sugestões inválidas separadas para revisão", **counts)
    audit(
        db, r.id, "browser-use", "recommendations", {"job_id": job.id, "run_id": job.external_id, "raw_response": raw, "validation": counts}
    )
    # Additional batches process only articles that still lack any analysis.
    db.flush()
    remaining = [a for a in db.scalars(select(Article).where(Article.review_id == r.id)) if not a.recommendation]
    if remaining:
        enqueue(db, r.id, "browser", "auto-next-" + job.id, {})
    if r.protocol.get("auto_search") and r.protocol.get("clickup_task_id"):
        from .delivery import request_delivery

        request_delivery(db, r, "clickup", "auto-screening-" + job.id, r.protocol["clickup_task_id"])


def handle(db, job):
    checkpoint(db, job)
    if job.kind == "pubmed":
        if db.bind.dialect.name == "postgresql" and not db.scalar(text("select pg_try_advisory_xact_lock(73941025)")):
            raise Later(10)
        ingest(db, job)
    elif job.kind == "planning":
        if not job.external_id:
            if job.payload.get("submission_started"):
                job.status = "needs_reconciliation"
                return
            r = db.get(Review, job.review_id)
            reserve_provider(db, job)
            job.payload = {**job.payload, "submission_started": True, "submitted_at": now()}
            event(db, job, "provider_submit", "Enviando contexto para planejamento")
            checkpoint(db, job, lock=True)
            db.commit()
            job.external_id = browser.submit({"title": r.title, **r.protocol}, [], planning=True)
            db.commit()
            raise Later(5)
        result = browser.poll(job.external_id, planning=True, observer=lambda raw: poll_events(db, job, raw))
        if result is None:
            if now() - job.payload.get("submitted_at", job.created_at) > 3600:
                raise ValueError("Planning timeout")
            raise Later(5)
        output, raw = result
        checked = []
        for concept in output.concepts:
            for term in concept.mesh:
                checkpoint(db, job)
                time.sleep(0.35)
                checked.append(pubmed.verify_mesh(term))
        job.payload = {**job.payload, "result": output.model_dump(mode="json"), "mesh_verification": checked}
        audit(
            db,
            job.review_id,
            "browser-use",
            "planning_proposed",
            {
                "run_id": job.external_id,
                "proposal": output.model_dump(mode="json"),
                "mesh_verification": checked,
                "prompt_version": "planning-1.0",
                "model": raw.get("model"),
                "cost_usd": raw.get("totalCostUsd"),
            },
        )
    elif job.kind == "browser":
        if db.scalar(select(Job.id).where(Job.review_id == job.review_id, Job.kind == "pubmed", Job.status.in_(["pending", "running"]))):
            raise Later(5)
        browse(db, job)
    elif job.kind == "pdf":
        a = db.get(Article, job.payload["article_id"])
        r = db.get(Review, job.review_id)
        if a.pdf.get("status") != "available":
            a.pdf = files.retrieve(a, r.owner_id)
        audit(db, r.id, "worker", "pdf_retrieval", {"article_id": a.id, **a.pdf})
    else:
        raise ValueError("Unknown job type")


def tick():
    token = str(uuid.uuid4())
    with Session() as db:
        if db.bind.dialect.name == "postgresql":
            if not db.scalar(text("select pg_try_advisory_xact_lock(73941027)")):
                return False
            from sqlalchemy import func

            active = db.scalar(select(func.count()).select_from(Job).where(Job.status == "running", Job.lease_until > now()))
            if active >= min(2, max(1, settings().worker_concurrency)):
                return False
        q = (
            select(Job)
            .where(
                or_(
                    and_(Job.status == "pending", Job.available_at <= now()),
                    and_(Job.status.in_(["running", "cancelling"]), Job.lease_until < now()),
                    and_(Job.status == "cancel_requested", Job.available_at <= now()),
                )
            )
            .order_by(Job.available_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = db.scalar(q)
        if not job:
            return False
        cancel = job.status in ("cancel_requested", "cancelling")
        old_status = job.status
        old_lease = job.lease_until
        payload = {**job.payload, "lease_token": token, "last_activity_at": now()}
        claimed = db.execute(
            update(Job)
            .where(
                Job.id == job.id, Job.status == old_status, *([Job.lease_until == old_lease] if db.bind.dialect.name == "sqlite" else [])
            )
            .values(status="cancelling" if cancel else "running", lease_until=now() + 300, payload=payload)
        )
        if not claimed.rowcount:
            db.rollback()
            return False
        jid = job.id
        event(db, job, "claimed", "Cancelando execução" if cancel else "Etapa em processamento")
        db.commit()
    with Session() as db:
        job = db.get(Job, jid)
        try:
            if cancel:
                if not job.external_id and job.payload.get("submission_started"):
                    age = now() - job.payload.get("cancel_requested_at", job.created_at)
                    job.status = "cancel_unknown" if age > 90 else "cancel_requested"
                    job.available_at = now() + 5
                    if age > 90:
                        event(
                            db,
                            job,
                            "cancel_unknown",
                            "Interrompido localmente; ID remoto não recuperado. Confira o provedor para confirmar interrupção de custos.",
                        )
                    db.commit()
                    return True
                if job.external_id and job.kind in ("browser", "planning"):
                    state = browser.cancel(job.external_id)
                    poll_events(db, job, state)
                job.status = "cancelled"
                job.error = ""
                event(db, job, "cancelled", "Cancelamento confirmado; dados recuperados preservados")
                db.commit()
                return True
            handle(db, job)
            persisted = checkpoint(db, job, lock=True)
            if persisted.get("progress"):
                job.payload = {**job.payload, "progress": persisted["progress"]}
            if job.status == "running":
                job.status = "done"
            job.payload = {**job.payload, "last_activity_at": now()}
            job.error = ""
            event(db, job, "completed", "Etapa concluída" if job.status == "done" else "Etapa concluída com alertas de validação")
            db.commit()
        except (Cancelled, LostLease):
            db.rollback()
            # Cancellation owner/next tick controls the final state; never revive this claim.
        except Later as later:
            try:
                checkpoint(db, job, lock=True)
                job.status = "pending"
                job.available_at = now() + later.seconds
                job.payload = {**job.payload, "last_activity_at": now()}
                db.commit()
            except (Cancelled, LostLease):
                db.rollback()
        except Exception as exc:
            db.rollback()
            job = db.get(Job, jid)
            if (
                job.payload.get("lease_token") != token
                or (not cancel and job.status in ("cancel_requested", "cancelling", "cancelled"))
                or job.status in ("cancelled", "cancel_unknown")
            ):
                return True
            job.attempts += 1
            job.error = type(exc).__name__
            ambiguous = job.kind in ("browser", "planning") and job.payload.get("submission_started") and not job.external_id
            deterministic = isinstance(exc, (InvalidProviderResult, __import__("pydantic").ValidationError)) or (
                isinstance(exc, ValueError) and job.external_id
            )
            if cancel:
                job.status = "cancel_unknown" if job.attempts >= 3 else "cancel_requested"
                job.available_at = now() + 30
                if job.attempts >= 3:
                    event(
                        db,
                        job,
                        "cancel_unknown",
                        "Falha na confirmação remota. Consulte o estado do provedor antes de considerar os custos interrompidos.",
                    )
            elif ambiguous:
                job.status = "needs_reconciliation"
            elif deterministic or job.attempts >= 3:
                job.status = "failed"
            else:
                job.status = "pending"
                job.available_at = now() + min(300, 5 * 2**job.attempts)
            audit(
                db,
                job.review_id,
                "worker",
                "job_error",
                {
                    "job_id": job.id,
                    "type": type(exc).__name__,
                    "attempt": job.attempts,
                    "state": job.status,
                    "retryable": not deterministic,
                },
            )
            db.commit()
            log.warning("Job %s: %s", jid, type(exc).__name__)
    return True


async def dispatch(stop):
    """Resident, bounded dispatcher; n8n is a fallback, not the queue clock."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    pool = ThreadPoolExecutor(max_workers=min(2, max(1, settings().worker_concurrency)), thread_name_prefix="fullmark")
    futures = set()
    delay = 0.25
    try:
        while not stop.is_set():
            done = {f for f in futures if f.done()}
            idle = False
            for f in done:
                try:
                    idle = not f.result() or idle
                except Exception:
                    log.exception("Dispatcher iteration failed")
                    idle = True
            futures -= done
            for _ in range(min(2, max(1, settings().worker_concurrency)) - len(futures)):
                futures.add(pool.submit(tick))
            delay = 5 if idle else 0.5
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        if not tick():
            time.sleep(2)


if __name__ == "__main__":
    main()
