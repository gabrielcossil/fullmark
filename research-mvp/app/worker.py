import json, logging, time
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
        with Session() as monitor:
            current = monitor.get(Job, job.id)
            current.payload = {**current.payload, "progress": {**value, "updated_at": now()}}
            monitor.commit()
    # Preserve the exact query and frozen filter snapshot before receiving provider results.
    context = dict(search.raw or {})
    records, raw = pubmed.search(search.query, search.max_records, progress=progress, sort=context.get("filters", {}).get("sort", "pub date"))
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
    search.raw = {**raw, "stats": {"imported":len(records), "new":new_count, "duplicates":duplicate_count}}
    if context.get("automatic_screening") and records:
        enqueue(db, job.review_id, "browser", "auto-"+search.id, {})
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


def browse(db, job):
    r = db.get(Review, job.review_id)
    if not job.external_id:
        if job.payload.get("submission_started"):
            job.status = "needs_reconciliation"
            job.error = "Submission outcome unknown; reconcile Browser Use dashboard before resubmitting"
            return
        articles = list(db.scalars(select(Article).where(Article.review_id == r.id)))
        if not articles:
            raise ValueError("Import PubMed records before browser research")
        # Durable marker before the non-idempotent provider request prevents blind paid resubmission.
        job.payload = {**job.payload, "submission_started": True, "article_ids": [a.id for a in articles]}
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
        raise Later(15)
    result = browser.poll(job.external_id)
    if result is None:
        if now() - job.created_at > 3600:
            raise ValueError("Browser run still active after one hour; inspect provider dashboard")
        raise Later(15)
    output, raw = result
    allowed = set(job.payload["article_ids"])
    seen = set()
    validated = []
    for finding in output.findings:
        if finding.article_id not in allowed or finding.article_id in seen:
            raise ValueError("Unknown or duplicate article ID in browser output")
        seen.add(finding.article_id)
        a = db.get(Article, finding.article_id)
        evidence = a.metadata_json.get("title", "") + "\n" + a.metadata_json.get("abstract", "")
        if finding.quote and finding.quote not in evidence:
            raise ValueError("Browser quote is not literal source evidence")
        if not finding.quote and finding.recommendation != "uncertain":
            raise ValueError("Recommendation without supporting evidence")
        validated.append((a, finding))
    if seen != allowed:
        raise ValueError("Incomplete browser screening output")
    for a, finding in validated:
        a.recommendation = {
            **finding.model_dump(),
            "run_id": job.external_id,
            "prompt_version": "1.0",
            "model": raw.get("model"),
            "at": now(),
        }
    audit(db, r.id, "browser-use", "recommendations", {"run_id": job.external_id, "raw_response": raw, "validated": True})


def handle(db, job):
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
            job.payload = {**job.payload, "submission_started": True}
            db.commit()
            job.external_id = browser.submit({"title":r.title, **r.protocol}, [], planning=True)
            db.commit()
            raise Later(15)
        result = browser.poll(job.external_id, planning=True)
        if result is None:
            if now()-job.created_at > 3600: raise ValueError("Planning timeout")
            raise Later(15)
        output, raw = result
        checked = []
        for concept in output.concepts:
            for term in concept.mesh:
                time.sleep(.35)
                checked.append(pubmed.verify_mesh(term))
        job.payload = {**job.payload, "result":output.model_dump(mode="json"), "mesh_verification":checked}
        audit(db, job.review_id, "browser-use", "planning_proposed", {"run_id":job.external_id,"proposal":output.model_dump(mode="json"),"mesh_verification":checked,"prompt_version":"planning-1.0"})
    elif job.kind == "browser":
        if db.scalar(select(Job.id).where(Job.review_id == job.review_id, Job.kind == "pubmed", Job.status != "done")):
            raise Later(15)
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
    # PostgreSQL row lock protects claims; CAS below protects the SQLite demo too.
    with Session() as db:
        q = (
            select(Job)
            .where(or_(and_(Job.status == "pending", Job.available_at <= now()), and_(Job.status == "running", Job.lease_until < now())))
            .order_by(Job.available_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = db.scalar(q)
        if not job:
            return False
        old_status = job.status
        old_lease = job.lease_until
        # PostgreSQL already holds the row lock; poolers may round float outputs.
        # Keep lease CAS only for SQLite, where SELECT FOR UPDATE is unavailable.
        claimed = db.execute(
            update(Job)
            .where(Job.id == job.id, Job.status == old_status,
                *([Job.lease_until == old_lease] if db.bind.dialect.name == "sqlite" else []))
            .values(status="running", lease_until=now() + 300)
        )
        if not claimed.rowcount:
            db.rollback()
            return False
        jid = job.id
        db.commit()
    with Session() as db:
        job = db.get(Job, jid)
        try:
            handle(db, job)
            if job.status == "running":
                job.status = "done"
            job.error = ""
            db.commit()
        except Later as later:
            job.status = "pending"
            job.available_at = now() + later.seconds
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(Job, jid)
            job.attempts += 1
            # Never store request URLs, headers, response bodies or credentials in errors.
            job.error = type(exc).__name__
            ambiguous = job.kind in ("browser", "planning") and job.payload.get("submission_started") and not job.external_id
            if ambiguous:
                job.status = "needs_reconciliation"
            elif job.attempts >= 3:
                job.status = "failed"
            else:
                job.status = "pending"
                job.available_at = now() + min(300, 15 * 2**job.attempts)
            audit(
                db,
                job.review_id,
                "worker",
                "job_error",
                {"job_id": job.id, "type": type(exc).__name__, "attempt": job.attempts, "state": job.status},
            )
            db.commit()
            log.warning("Job %s: %s", jid, type(exc).__name__)
    return True


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        if not tick():
            time.sleep(2)


if __name__ == "__main__":
    main()
