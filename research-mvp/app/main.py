import io, json, secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
import httpx
from fastapi import FastAPI, Depends, Header, HTTPException, Response, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, text, func
from .config import settings
from .db import Base, engine, Session, Review, Search, Article, Audit, Job, audit, enqueue, now
from .schemas import ReviewCreate, SearchCreate, DecisionCreate, ExtractionCreate, PasswordSet, BulkDecision, IntakeCreate
from .service import digest, owned, article_for, decide, snapshot, prisma
from . import files, exports
from .research import Filters, build_query


@asynccontextmanager
async def lifespan(app):
    if settings().environment != "production":
        Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Fullmark Research", version="0.2.0", lifespan=lifespan)


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
        "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; font-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    )
    return response


@app.get("/", response_class=HTMLResponse)
def home():
    return Path(__file__).with_name("static").joinpath("index.html").read_text()


@app.get("/static/{name}")
def asset(name: str):
    if name not in ("app.js", "style.css", "montserrat.woff2"):
        raise HTTPException(404)
    return Response(
        Path(__file__).with_name("static").joinpath(name).read_bytes(),
        media_type="font/woff2" if name.endswith(".woff2") else "text/javascript" if name.endswith(".js") else "text/css",
    )


@app.get("/config")
def public_config():
    return {"demo_mode": settings().demo_mode, "auth_configured": bool(settings().supabase_url)}


@app.get("/health/live")
def live():
    return {"status": "ok", "version": "0.2.0"}


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
        {
            "id": r.id,
            "title": r.title,
            "approved_at": r.approved_at,
            "article_count": db.scalar(select(func.count()).select_from(Article).where(Article.review_id == r.id)),
        }
        for r in db.scalars(select(Review).where(Review.owner_id == actor).order_by(Review.created_at.desc()))
    ]


@app.post("/reviews", status_code=201)
def create(body: ReviewCreate, db: DB, actor: User):
    protocol = body.protocol.model_dump(mode="json")
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
    if r.protocol.get("auto_search"):
        plans = list(
            db.scalars(
                select(Job).where(Job.review_id == rid, Job.kind == "planning", Job.status == "done").order_by(Job.created_at.desc())
            )
        )
        if not plans or not plans[0].payload.get("result", {}).get("strategies"):
            raise HTTPException(409, "Conclua as sugestões de estratégias antes de aprovar com início automático, ou desmarque essa opção.")
        if plans and plans[0].payload.get("result", {}).get("strategies"):
            query = plans[0].payload["result"]["strategies"][0]["query"]
            previous = db.scalar(select(Search.id).where(Search.review_id == rid, Search.request_key == "approved-auto-search"))
            if not previous:
                filters = Filters.model_validate(r.protocol.get("filters", {}))
                s = Search(
                    review_id=rid,
                    request_key="approved-auto-search",
                    query=build_query(query, filters),
                    max_records=r.protocol.get("max_records", 50),
                    raw={"base_query": query, "filters": filters.model_dump(mode="json"), "automatic_screening": True},
                )
                db.add(s)
                db.flush()
                enqueue(db, rid, "pubmed", s.id, {"search_id": s.id})
                audit(db, rid, actor, "approved_auto_search_requested", {"query": s.query})
    return {"approved": True, "hash": r.protocol_hash}


@app.get("/reviews/{rid}")
def detail(rid: str, db: DB, actor: User):
    return snapshot(db, owned(db, rid, actor))


@app.post("/reviews/{rid}/searches", status_code=202)
def search(rid: str, body: SearchCreate, db: DB, actor: User, idempotency_key: Annotated[str, Header(min_length=8, max_length=100)]):
    r = owned(db, rid, actor, True)
    if not r.approved_at:
        raise HTTPException(409, "Aprove o protocolo")
    filters = body.filters or Filters.model_validate(r.protocol.get("filters", {}))
    existing = db.scalar(select(Search).where(Search.review_id == rid, Search.request_key == idempotency_key))
    if existing:
        context = existing.raw.get("fullmark", existing.raw)
        if (
            (context.get("base_query", existing.query), existing.max_records) != (body.query, body.max_records)
            or context.get("filters", {}) != filters.model_dump(mode="json")
            or context.get("automatic_screening", False) != body.automatic_screening
        ):
            raise HTTPException(409, "Chave já usada com outros parâmetros")
        return {"search_id": existing.id}
    query = build_query(body.query, filters)
    s = Search(
        review_id=rid,
        request_key=idempotency_key,
        query=query,
        max_records=body.max_records,
        raw={"base_query": body.query, "filters": filters.model_dump(mode="json"), "automatic_screening": body.automatic_screening},
    )
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
    active = db.scalar(
        select(Job).where(Job.review_id == rid, Job.kind == "browser", Job.status.in_(["pending", "running", "needs_reconciliation"]))
    )
    if active:
        return {"job_id": active.id}
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
    elif kind == "csv":
        data = exports.history_csv(snap)
        mime = "text/csv; charset=utf-8"
        ext = "csv"
    elif kind == "zip":
        data = exports.package(snap)
        mime = "application/zip"
        ext = "zip"
    elif kind == "md":
        data = exports.methodology(snap).encode()
        mime = "text/markdown; charset=utf-8"
        ext = "md"
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
    if j.kind in ("browser", "planning") and not j.external_id:
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
    if j.kind not in ("browser", "planning") or j.status != "needs_reconciliation":
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
    if j.kind == "browser" and (
        not all(aid in run.get("task", "") for aid in j.payload.get("article_ids", [])) or not j.payload.get("article_ids")
    ):
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


@app.get("/research/options")
def research_options():
    from .research import PUBLICATION_TYPES, LANGUAGES, AGES

    return {"study_types": {k: v[0] for k, v in PUBLICATION_TYPES.items()}, "languages": LANGUAGES, "ages": list(AGES), "max_records": 200}


@app.post("/documents/extract")
async def document_extract(request: Request, actor: User, x_filename: Annotated[str, Header(max_length=300)]):
    from .research import extract_document
    from urllib.parse import unquote

    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(413, "Limite de 10 MB por documento")
    try:
        return extract_document(bytes(data), unquote(x_filename))
    except Exception as e:
        raise HTTPException(422, str(e) if isinstance(e, ValueError) else "Documento inválido ou sem texto legível")


@app.put("/reviews/{rid}/draft")
def update_draft(rid: str, body: ReviewCreate, db: DB, actor: User):
    r = owned(db, rid, actor, True)
    if r.approved_at:
        raise HTTPException(409, "Protocolo aprovado é imutável. Crie outra pesquisa para mudar os critérios.")
    r.title = body.title
    r.protocol = body.protocol.model_dump(mode="json")
    r.protocol_hash = digest(r.protocol)
    audit(db, rid, actor, "draft_updated", {"protocol": r.protocol, "hash": r.protocol_hash})
    return {"saved": True}


@app.post("/reviews/{rid}/plan", status_code=202)
def planning(rid: str, db: DB, actor: User, idempotency_key: Annotated[str, Header(min_length=8, max_length=100)]):
    r = owned(db, rid, actor, True)
    if not settings().browser_use_api_key or not settings().browser_network_policy_id:
        raise HTTPException(503, "Assistente ainda não configurado")
    active = db.scalar(
        select(Job).where(Job.review_id == rid, Job.kind == "planning", Job.status.in_(["pending", "running", "needs_reconciliation"]))
    )
    if active:
        return {"job_id": active.id}
    j = enqueue(db, rid, "planning", idempotency_key, {})
    audit(db, rid, actor, "planning_requested", {"job_id": j.id, "approved_protocol_unchanged": bool(r.approved_at)})
    return {"job_id": j.id}


@app.post("/reviews/{rid}/recommendations/accept")
def accept_recommendations(rid: str, body: BulkDecision, db: DB, actor: User):
    r = owned(db, rid, actor, True)
    selected = []
    from .service import decisions

    latest = decisions(db, rid)
    for aid in set(body.article_ids):
        a = article_for(db, rid, aid)
        if a.recommendation.get("recommendation") != "include":
            raise HTTPException(422, "Selecione somente recomendações de inclusão")
        if (aid, "full_text") in latest:
            raise HTTPException(409, "Artigo já avaliado em texto completo")
        selected.append(a)
    for a in selected:
        decide(db, r, a, DecisionCreate(stage="title_abstract", verdict="include", reason=body.reason), actor)
    return {"accepted": len(selected), "next": "PDFs legais agendados; texto completo ainda requer avaliação humana"}


@app.post("/reviews/{rid}/deliver/drive", status_code=202)
def deliver_drive(rid: str, db: DB, actor: User, idempotency_key: Annotated[str, Header(min_length=8, max_length=100)]):
    from .delivery import request_delivery

    r = owned(db, rid, actor, True)
    if not r.approved_at:
        raise HTTPException(409, "Aprove o protocolo primeiro")
    j = request_delivery(db, r, "drive", idempotency_key)
    return {"job_id": j.id, "message": "Entrega no Drive solicitada; os arquivos serão enviados à pasta Fullmark Research Studio."}


@app.post("/reviews/{rid}/deliver/clickup", status_code=202)
def deliver_clickup(rid: str, body: dict, db: DB, actor: User, idempotency_key: Annotated[str, Header(min_length=8, max_length=100)]):
    import re
    from .delivery import request_delivery

    r = owned(db, rid, actor, True)
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,100}", body.get("task_id", "")):
        raise HTTPException(422, "Informe o ID da tarefa")
    j = request_delivery(db, r, "clickup", idempotency_key, body["task_id"])
    return {"job_id": j.id}


@app.get("/internal/deliveries/next", dependencies=[Depends(internal)])
def next_delivery(db: DB):
    from .delivery import claim

    return claim(db)


@app.post("/internal/deliveries/{jid}/ack", dependencies=[Depends(internal)])
def ack_delivery(jid: str, body: dict, db: DB):
    from .delivery import acknowledge

    return acknowledge(db, jid, body)


@app.get("/internal/deliveries/{jid}/file/{index}", dependencies=[Depends(internal)])
def download_delivery(jid: str, index: int, db: DB):
    from .delivery import asset

    data, mime, name = asset(db, jid, index)
    return Response(data, media_type=mime, headers={"Content-Disposition": 'attachment; filename="' + name + '"'})


@app.post("/internal/intake", status_code=202, dependencies=[Depends(internal)])
def intake(body: IntakeCreate, db: DB):
    from uuid import UUID

    owner = settings().automation_owner_id
    try:
        owner = str(UUID(owner))
    except ValueError:
        raise HTTPException(503, "Configure o proprietário da entrada automática")
    if db.bind.dialect.name == "postgresql":
        db.execute(text("select pg_advisory_xact_lock(73941026)"))
    for r in db.scalars(select(Review).where(Review.owner_id == owner)):
        if r.protocol.get("clickup_task_id") == body.task_id:
            return {"review_id": r.id, "created": False}
    p = {
        "question": "Pergunta em elaboração para: " + body.title,
        "inclusion": ["Rascunho: revisar critérios sugeridos antes de aprovar."],
        "exclusion": ["Rascunho: revisar critérios sugeridos antes de aprovar."],
        "pico": {},
        "database": "pubmed",
        "max_records": body.max_records,
        "filters": Filters().model_dump(mode="json"),
        "observations": "Entrada automática autorizada pelo comando do ClickUp; aguarda aprovação humana.",
        "source_document": {"filename": "Ficha ClickUp " + body.task_id, "text": body.production_text},
        "clickup_task_id": body.task_id,
        "auto_search": True,
    }
    r = Review(owner_id=owner, title=body.title, protocol=p, protocol_hash=digest(p))
    db.add(r)
    db.flush()
    enqueue(db, r.id, "planning", "intake-" + body.task_id, {})
    audit(db, r.id, "clickup", "intake_received", {"task_id": body.task_id, "needs_human_protocol_approval": True})
    return {"review_id": r.id, "created": True, "next": "Planejamento na fila. A pesquisa só começa após aprovação do protocolo."}
