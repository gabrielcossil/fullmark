import hashlib, json
from sqlalchemy import select
from fastapi import HTTPException
from .db import Review, Article, Decision, Record, Audit, Job, Search, audit, enqueue, now
from .schemas import DecisionCreate


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def owned(db, review_id, actor, lock=False):
    q = select(Review).where(Review.id == review_id, Review.owner_id == actor)
    if lock:
        q = q.with_for_update()
    r = db.scalar(q)
    if not r:
        raise HTTPException(404, "Pesquisa não encontrada")
    return r


def article_for(db, review_id, article_id):
    a = db.get(Article, article_id)
    if not a or a.review_id != review_id:
        raise HTTPException(404, "Artigo não encontrado")
    return a


def decisions(db, review_id):
    result = {}
    for d in db.scalars(select(Decision).where(Decision.review_id == review_id).order_by(Decision.created_at, Decision.id)):
        result[(d.article_id, d.stage)] = d
    return result


def decide(db, r, a, body: DecisionCreate, actor):
    if not r.approved_at:
        raise HTTPException(409, "Aprove o protocolo primeiro")
    latest = decisions(db, r.id)
    if body.stage == "title_abstract":
        if body.verdict == "not_retrieved":
            raise HTTPException(422, "Use not_retrieved somente em texto completo")
        if (a.id, "full_text") in latest:
            raise HTTPException(409, "Texto completo já decidido; crie uma revisão do protocolo para reabrir a triagem")
    else:
        previous = latest.get((a.id, "title_abstract"))
        if not previous or previous.verdict != "include":
            raise HTTPException(409, "Inclua título/resumo antes")
        if body.verdict not in ("not_retrieved", "uncertain") and a.pdf.get("status") != "available":
            raise HTTPException(409, "Texto completo legal ainda não disponível")
        if body.verdict == "not_retrieved" and a.pdf.get("status") == "available":
            raise HTTPException(409, "PDF disponível; avalie o texto completo")
    d = Decision(review_id=r.id, article_id=a.id, actor=actor, **body.model_dump())
    db.add(d)
    audit(db, r.id, actor, "decision", {"article_id": a.id, **body.model_dump(), "protocol_hash": r.protocol_hash})
    if body.stage == "title_abstract" and body.verdict == "include":
        enqueue(db, r.id, "pdf", a.id, {"article_id": a.id})
    db.flush()
    return d


def prisma(db, rid):
    articles = list(db.scalars(select(Article).where(Article.review_id == rid)))
    records = list(db.scalars(select(Record).where(Record.review_id == rid)))
    latest = decisions(db, rid)
    n = len(articles)
    counts = dict(
        identified=len(records),
        duplicates_removed=len(records) - n,
        screened=0,
        title_abstract_excluded=0,
        title_abstract_pending=0,
        reports_sought=0,
        reports_not_retrieved=0,
        reports_retrieval_pending=0,
        reports_available=0,
        reports_assessed=0,
        full_text_excluded=0,
        full_text_pending=0,
        included_reports=0,
    )
    reasons = {}
    for a in articles:
        ta = latest.get((a.id, "title_abstract"))
        ft = latest.get((a.id, "full_text"))
        if not ta or ta.verdict == "uncertain":
            counts["title_abstract_pending"] += 1
            continue
        counts["screened"] += 1
        if ta.verdict == "exclude":
            counts["title_abstract_excluded"] += 1
            continue
        counts["reports_sought"] += 1
        if ft and ft.verdict == "not_retrieved":
            counts["reports_not_retrieved"] += 1
            continue
        if a.pdf.get("status") != "available":
            counts["reports_retrieval_pending"] += 1
            continue
        counts["reports_available"] += 1
        if not ft or ft.verdict == "uncertain":
            counts["full_text_pending"] += 1
            continue
        counts["reports_assessed"] += 1
        if ft.verdict == "include":
            counts["included_reports"] += 1
        else:
            counts["full_text_excluded"] += 1
            reasons[ft.reason] = reasons.get(ft.reason, 0) + 1
    counts["full_text_exclusion_reasons"] = reasons
    counts["study_count"] = None
    counts["note"] = (
        "Contagens de registros e relatórios. Estudos distintos exigem agrupamento humano. Busca limitada a até 200 registros por execução; total_found não é contagem de registros importados."
    )
    counts["complete"] = not any(
        counts[k] for k in ("title_abstract_pending", "reports_retrieval_pending", "full_text_pending")
    ) and not db.scalar(
        select(Job.id).where(Job.review_id == rid, Job.status.in_(["pending", "running", "failed", "needs_reconciliation"]))
    )
    return counts


def snapshot(db, r):
    def rows(cls):
        result = [{c.name: getattr(o, c.name) for c in cls.__table__.columns} for o in db.scalars(select(cls).where(cls.review_id == r.id))]
        if cls is Job:
            for row in result:
                row["payload"] = {k: v for k, v in row["payload"].items() if k != "snapshot"}
        return result

    return {
        "review": {c.name: getattr(r, c.name) for c in Review.__table__.columns},
        "prisma": prisma(db, r.id),
        "articles": rows(Article),
        "records": rows(Record),
        "searches": rows(Search),
        "decisions": rows(Decision),
        "audit": rows(Audit),
        "jobs": rows(Job),
        "exported_at": now(),
    }
