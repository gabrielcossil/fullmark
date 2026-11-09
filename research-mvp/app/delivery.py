"""Durable n8n outbox. Never blindly retry an uncertain external write."""

import json, re
from sqlalchemy import select
from fastapi import HTTPException
from .db import Job, Article, Review, audit, now
from . import exports, files
from .service import snapshot, decisions


def request_delivery(db, r, kind, key, task_id=""):
    existing = db.scalar(select(Job).where(Job.review_id == r.id, Job.kind == kind, Job.request_key == key))
    if existing:
        return existing
    snap = snapshot(db, r)
    assets = [
        {"name": "matriz.xlsx", "kind": "xlsx"},
        {"name": "prisma.svg", "kind": "svg"},
        {"name": "historico-pubmed.csv", "kind": "csv"},
        {"name": "historico-completo.json", "kind": "json"},
        {"name": "metodologia.md", "kind": "md"},
    ]
    latest = decisions(db, r.id)
    for a in snap["articles"]:
        d = latest.get((a["id"], "title_abstract"))
        if d and d.verdict == "include" and a["pdf"].get("status") == "available":
            assets.append({"name": "PMID-" + a["metadata_json"].get("pmid", a["id"]) + ".pdf", "kind": "pdf", "path": a["pdf"]["path"]})
    j = Job(
        review_id=r.id,
        kind=kind,
        request_key=key,
        status="delivery_pending",
        payload={"snapshot": snap, "assets": assets, "completed": {}, "task_id": task_id, "cursor": 0},
    )
    db.add(j)
    db.flush()
    audit(
        db,
        r.id,
        r.owner_id,
        "delivery_requested",
        {"job_id": j.id, "kind": kind, "task_id": task_id, "asset_count": len(assets), "snapshot_at": snap["exported_at"]},
    )
    return j


def claim(db):
    # Lost acknowledgements require reconciliation, not duplicate folders/files/comments.
    for expired in db.scalars(
        select(Job).where(Job.status == "delivery_running", Job.lease_until < now()).with_for_update(skip_locked=True)
    ):
        expired.status = "needs_reconciliation"
        expired.error = "External write outcome unknown; check n8n before retrying"
    j = db.scalar(select(Job).where(Job.status == "delivery_pending").order_by(Job.created_at).limit(1).with_for_update(skip_locked=True))
    if not j:
        return []
    j.status = "delivery_running"
    j.lease_until = now() + 600
    p = j.payload
    r = db.get(Review, j.review_id)
    common = {"job_id": j.id, "title": r.title, "cursor": p.get("cursor", 0)}
    if j.kind == "clickup":
        return [
            {
                **common,
                "action": "clickup",
                "task_id": p["task_id"],
                "comment": "Fullmark Research · Pesquisa processada: "
                + r.title
                + "\nPubMed: "
                + str(len(p["snapshot"]["articles"]))
                + " referências únicas; "
                + str(p["snapshot"]["prisma"]["included_reports"])
                + " relatórios incluídos.\nProtocolo e decisões: https://fullmark-research-api.onrender.com/?review="
                + r.id
                + "\nAs recomendações e pendências aguardam aprovação humana no painel.",
            }
        ]
    if not p.get("folder_id"):
        return [{**common, "action": "folder", "folder_name": r.title[:150] + " · " + j.id[:8]}]
    i = p["cursor"]
    return [
        {
            **common,
            "action": "file",
            "folder_id": p["folder_id"],
            "name": p["assets"][i]["name"],
            "download_url": "https://fullmark-research-api.onrender.com/internal/deliveries/" + j.id + "/file/" + str(i),
        }
    ]


def acknowledge(db, jid, body):
    j = db.scalar(select(Job).where(Job.id == jid).with_for_update())
    if not j or j.kind not in ("drive", "clickup"):
        raise HTTPException(404)
    p = dict(j.payload)
    remote = str(body.get("remote_id", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", remote):
        raise HTTPException(422, "Invalid external ID")
    if j.status == "done":
        return {"done": True}
    if j.status != "delivery_running":
        raise HTTPException(409, "Delivery is not claimed")
    if body.get("action") == "folder" and j.kind == "drive" and not p.get("folder_id"):
        p["folder_id"] = remote
        j.status = "delivery_pending"
    elif body.get("action") == "file" and j.kind == "drive" and body.get("cursor") == p["cursor"]:
        p["completed"] = {**p["completed"], str(p["cursor"]): remote}
        p["cursor"] += 1
        j.status = "done" if p["cursor"] >= len(p["assets"]) else "delivery_pending"
    elif body.get("action") == "clickup" and j.kind == "clickup":
        p["comment_id"] = remote
        j.status = "done"
    else:
        raise HTTPException(409, "Mismatched delivery acknowledgement")
    j.payload = p
    audit(
        db,
        j.review_id,
        "n8n",
        "delivery_progress",
        {"job_id": j.id, "action": body.get("action"), "remote_id": remote, "cursor": p["cursor"], "state": j.status},
    )
    return {"done": j.status == "done"}


def asset(db, jid, index):
    j = db.get(Job, jid)
    if not j or j.kind != "drive":
        raise HTTPException(404)
    try:
        a = j.payload["assets"][index]
    except (IndexError, KeyError):
        raise HTTPException(404)
    if index < 0:
        raise HTTPException(404)
    snap = j.payload["snapshot"]
    kind = a["kind"]
    if kind == "pdf":
        data = files.get(a["path"])
        mime = "application/pdf"
    elif kind == "xlsx":
        data = exports.xlsx(snap)
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif kind == "svg":
        data = exports.prisma_svg(snap["prisma"])
        mime = "image/svg+xml"
    elif kind == "csv":
        data = exports.history_csv(snap)
        mime = "text/csv"
    elif kind == "md":
        data = exports.methodology(snap).encode()
        mime = "text/markdown"
    else:
        data = json.dumps(snap, ensure_ascii=False, indent=2).encode()
        mime = "application/json"
    return data, mime, a["name"]
