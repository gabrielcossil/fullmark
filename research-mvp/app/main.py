import io, json, secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
import httpx
from fastapi import FastAPI, Depends, Header, HTTPException, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import select, text
from .config import settings
from .db import Base, engine, Session, Review, Search, Article, Audit, Job, audit, enqueue, now
from .schemas import ReviewCreate, SearchCreate, DecisionCreate, ExtractionCreate, PasswordSet
from .service import digest, owned, article_for, decide, snapshot, prisma
from . import files, exports


@asynccontextmanager
async def lifespan(app):
    if settings().environment != "production":
        Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Fullmark Research", version="0.1.0", lifespan=lifespan)


def session():
    with Session() as db:
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


DB = Annotated[object, Depends(session)]


def user(authorization: Annotated[str | None, Header()] = None):
    if settings().demo_mode:
        if authorization == "Bearer local-demo":
            return "00000000-0000-0000-0000-000000000001"
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Entre na sua conta")
    s = settings()
    if not s.supabase_url:
        raise HTTPException(503, "Supabase Auth não configurado")
    try:
        with httpx.Client(timeout=10) as c:
            r = c.get(s.supabase_url + "/auth/v1/user", headers={"apikey": s.supabase_publishable_key, "Authorization": authorization})
        if r.status_code != 200:
            raise HTTPException(401, "Sessão inválida")
        identity = r.json()
        if s.allowed_emails.strip():
            allowed = {email.strip().casefold() for email in s.allowed_emails.split(",") if email.strip()}
            if identity.get("email", "").casefold() not in allowed or not identity.get("email_confirmed_at"):
                raise HTTPException(403, "Esta conta não está autorizada no painel Fullmark")
        return identity["id"]
    except (httpx.HTTPError, KeyError):
        raise HTTPException(503, "Autenticação indisponível")


User = Annotated[str, Depends(user)]


def internal(x_internal_token: Annotated[str | None, Header()] = None):
    if not settings().internal_token or not secrets.compare_digest(x_internal_token or "", settings().internal_token):
        raise HTTPException(401, "Credencial interna inválida")


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    )
    return response


@app.get("/", response_class=HTMLResponse)
def home():
    return Path(__file__).with_name("static").joinpath("index.html").read_text()


@app.get("/static/{name}")
def asset(name: str):
    if name not in ("app.js", "style.css"):
        raise HTTPException(404)
    return Response(
        Path(__file__).with_name("static").joinpath(name).read_bytes(), media_type="text/javascript" if name.endswith(".js") else "text/css"
    )


@app.get("/config")
def public_config():
    return {"demo_mode": settings().demo_mode, "auth_configured": bool(settings().supabase_url)}


@app.get("/health/live")
def live():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/health/ready")
def ready(db: DB):
    try:
        db.execute(text("select id from fm_reviews limit 1"))
    except Exception:
        raise HTTPException(503, "Migrações pendentes ou banco indisponível")
    return {"status": "ready"}


@app.post("/auth/login")
def login(body: dict):
    if settings().demo_mode:
        return {"access_token": "local-demo", "refresh_token": ""}
    if not settings().supabase_url:
        raise HTTPException(503, "Supabase não configurado")
    # Credentials transit only to the configured Supabase Auth; never stored or logged.
    if set(body) != {"email", "password"}:
        raise HTTPException(422, "Informe email e senha")
    with httpx.Client(timeout=15) as c:
        r = c.post(
            settings().supabase_url + "/auth/v1/token?grant_type=password",
            headers={"apikey": settings().supabase_publishable_key},
            json=body,
        )
    if r.status_code != 200:
        raise HTTPException(401, "Não foi possível entrar")
    data = r.json()
    return {k: data[k] for k in ("access_token", "refresh_token", "expires_in")}


@app.post("/auth/refresh")
def refresh(body: dict):
    if not settings().supabase_url:
        raise HTTPException(503, "Supabase não configurado")
    with httpx.Client(timeout=15) as c:
        r = c.post(
            settings().supabase_url + "/auth/v1/token?grant_type=refresh_token",
            headers={"apikey": settings().supabase_publishable_key},
            json={"refresh_token": body.get("refresh_token", "")},
        )
    if r.status_code != 200:
        raise HTTPException(401, "Entre novamente")
    data = r.json()
    return {k: data[k] for k in ("access_token", "refresh_token", "expires_in")}


@app.get("/reviews")
def reviews(db: DB, actor: User):
    return [
        {"id": r.id, "title": r.title, "approved_at": r.approved_at}
        for r in db.scalars(select(Review).where(Review.owner_id == actor).order_by(Review.created_at.desc()))
    ]


@app.post("/reviews", status_code=201)
def create(body: ReviewCreate, db: DB, actor: User):
    protocol = body.protocol.model_dump()
    r = Review(owner_id=actor, title=body.title, protocol=protocol, protocol_hash=digest(protocol))
    db.add(r)
    db.flush()
    audit(db, r.id, actor, "protocol_created", {"hash": r.protocol_hash, "protocol": protocol})
    return {"id": r.id}


@app.post("/reviews/{rid}/approve")
def approve(rid: str, db: DB, actor: User):
    r = owned(db, rid, actor, True)
    if not r.approved_at:
        r.approved_at = now()
        audit(db, rid, actor, "protocol_approved", {"hash": r.protocol_hash})
    return {"approved": True, "hash": r.protocol_hash}


@app.get("/reviews/{rid}")
def detail(rid: str, db: DB, actor: User):
    return snapshot(db, owned(db, rid, actor))


@app.post("/reviews/{rid}/searches", status_code=202)
def search(rid: str, body: SearchCreate, db: DB, actor: User, idempotency_key: Annotated[str, Header(min_length=8, max_length=100)]):
    r = owned(db, rid, actor, True)
    if not r.approved_at:
        raise HTTPException(409, "Aprove o protocolo")
    existing = db.scalar(select(Search).where(Search.review_id == rid, Search.request_key == idempotency_key))
    if existing:
        if (existing.query, existing.max_records) != (body.query, body.max_records):
            raise HTTPException(409, "Chave já usada com outros parâmetros")
        return {"search_id": existing.id}
    s = Search(review_id=rid, request_key=idempotency_key, query=body.query, max_records=body.max_records)
    db.add(s)
    db.flush()
    j = enqueue(db, rid, "pubmed", s.id, {"search_id": s.id})
    audit(db, rid, actor, "search_requested", body.model_dump())
    return {"search_id": s.id, "job_id": j.id}


@app.post("/reviews/{rid}/browser", status_code=202)
def browser_job(rid: str, db: DB, actor: User, idempotency_key: Annotated[str, Header(min_length=8, max_length=100)]):
    r = owned(db, rid, actor, True)
    if not r.approved_at:
        raise HTTPException(409, "Aprove o protocolo")
    from .config import settings

    if not settings().browser_use_api_key or not settings().browser_network_policy_id:
        raise HTTPException(503, "Configure Browser Use e a política de domínios na hospedagem")
    if db.scalar(select(Job.id).where(Job.review_id == rid, Job.kind == "pubmed", Job.status != "done")):
        raise HTTPException(409, "Conclua as buscas PubMed antes")
    j = enqueue(db, rid, "browser", idempotency_key, {})
    audit(db, rid, actor, "browser_requested", {"job_id": j.id})
    return {"job_id": j.id}


@app.post("/reviews/{rid}/articles/{aid}/decisions")
def decision(rid: str, aid: str, body: DecisionCreate, db: DB, actor: User):
    r = owned(db, rid, actor, True)
    d = decide(db, r, article_for(db, rid, aid), body, actor)
    return {"decision_id": d.id}


@app.post("/reviews/{rid}/articles/{aid}/extraction")
def extraction(rid: str, aid: str, body: ExtractionCreate, db: DB, actor: User):
    owned(db, rid, actor, True)
    a = article_for(db, rid, aid)
    if a.pdf.get("status") != "available":
        raise HTTPException(409, "PDF indisponível")
    pages = json.loads(files.get(a.pdf["text_path"]))
    for item in body.items:
        if item.page > len(pages) or item.quote not in pages[item.page - 1]:
            raise HTTPException(422, "Citação não encontrada na página indicada; PDF pode precisar de OCR")
    a.extraction = {"items": [i.model_dump() for i in body.items], "reviewed_by": actor, "at": now()}
    audit(db, rid, actor, "extraction_verified", {"article_id": aid, **a.extraction})
    return {"saved": True}


@app.get("/reviews/{rid}/articles/{aid}/pdf")
def pdf(rid: str, aid: str, db: DB, actor: User):
    owned(db, rid, actor)
    a = article_for(db, rid, aid)
    if a.pdf.get("status") != "available":
        raise HTTPException(404)
    return Response(
        files.get(a.pdf["path"]), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{aid}.pdf"'}
    )


@app.get("/reviews/{rid}/prisma")
def get_prisma(rid: str, db: DB, actor: User):
    owned(db, rid, actor)
    return prisma(db, rid)


@app.get("/reviews/{rid}/export/{kind}")
def export(rid: str, kind: str, db: DB, actor: User):
    snap = snapshot(db, owned(db, rid, actor))
    if kind == "xlsx":
        data = exports.xlsx(snap)
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ext = "xlsx"
    elif kind == "svg":
        data = exports.prisma_svg(snap["prisma"])
        mime = "image/svg+xml"
        ext = "svg"
    elif kind == "json":
        data = json.dumps(snap, ensure_ascii=False, indent=2).encode()
        mime = "application/json"
        ext = "json"
    else:
        raise HTTPException(404)
    return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="fullmark-{rid}.{ext}"'})


@app.post("/internal/tick", dependencies=[Depends(internal)])
def tick():
    from .worker import tick

    return {"processed": tick()}


@app.get("/internal/queue", dependencies=[Depends(internal)])
def queue(db: DB):
    from sqlalchemy import func

    return dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())


@app.post("/reviews/{rid}/jobs/{jid}/retry", status_code=202)
def retry_job(rid: str, jid: str, db: DB, actor: User):
    owned(db, rid, actor, True)
    j = db.get(Job, jid)
    if not j or j.review_id != rid:
        raise HTTPException(404)
    if j.status != "failed":
        raise HTTPException(409, "Somente tarefas com falha podem ser reenviadas")
    if j.kind == "browser" and not j.external_id:
        raise HTTPException(409, "Reconcilie a execução no Browser Use primeiro")
    j.status = "pending"
    j.attempts = 0
    j.available_at = now()
    j.error = ""
    audit(db, rid, actor, "job_retry", {"job_id": jid})
    return {"job_id": jid}


@app.post("/reviews/{rid}/jobs/{jid}/reconcile", status_code=202)
def reconcile_job(rid: str, jid: str, body: dict, db: DB, actor: User):
    from uuid import UUID
    from . import browser

    owned(db, rid, actor, True)
    j = db.get(Job, jid)
    if not j or j.review_id != rid:
        raise HTTPException(404)
    if j.kind != "browser" or j.status != "needs_reconciliation":
        raise HTTPException(409, "Esta tarefa não precisa de reconciliação")
    try:
        run_id = str(UUID(body["run_id"]))
    except (KeyError, ValueError, TypeError):
        raise HTTPException(422, "Informe o ID da execução no Browser Use")
    with browser.client() as c:
        response = c.get(f"/runs/{run_id}")
        response.raise_for_status()
        run = response.json()
    # Do not bind a different research task to this job.
    if not all(aid in run.get("task", "") for aid in j.payload.get("article_ids", [])) or not j.payload.get("article_ids"):
        raise HTTPException(409, "Execução não corresponde aos artigos desta pesquisa")
    j.external_id = run_id
    j.status = "pending"
    j.available_at = now()
    j.attempts = 0
    j.error = ""
    audit(db, rid, actor, "browser_reconciled", {"job_id": jid, "run_id": run_id})
    return {"job_id": jid}


@app.get("/auth/me")
def profile(actor: User, authorization: Annotated[str | None, Header()] = None):
    if settings().demo_mode and authorization == "Bearer local-demo":
        return {"id": actor, "email": "Demonstração local"}
    with httpx.Client(timeout=15) as c:
        r = c.get(
            settings().supabase_url + "/auth/v1/user",
            headers={"apikey": settings().supabase_publishable_key, "Authorization": authorization},
        )
    if r.status_code != 200 or r.json().get("id") != actor:
        raise HTTPException(401, "Sessão inválida")
    return {"id": actor, "email": r.json().get("email", "")}


@app.post("/auth/password")
def password_set(body: PasswordSet, actor: User, authorization: Annotated[str | None, Header()] = None):
    if settings().demo_mode:
        raise HTTPException(409, "Não há senha de conta na demonstração local")
    with httpx.Client(timeout=15) as c:
        r = c.put(
            settings().supabase_url + "/auth/v1/user",
            headers={"apikey": settings().supabase_publishable_key, "Authorization": authorization},
            json={"password": body.password},
        )
    if r.status_code != 200:
        raise HTTPException(400, "Não foi possível definir a senha. Use pelo menos 12 caracteres e tente novamente.")
    return {"updated": True}
