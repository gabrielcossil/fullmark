import io, json, zipfile
import pytest
from app import db, research, exports, delivery
from app.service import snapshot


def test_filters_query_and_dates():
    f = research.Filters(
        study_types=["randomized", "cohort"],
        languages=["english", "portuguese"],
        species="humans",
        date_from="2020-01-01",
        date_to="2026-11-09",
        exclude_preprints=True,
    )
    q = research.build_query("exercise OR balance", f)
    assert q.startswith("(exercise OR balance) AND (Randomized Controlled Trial[pt] OR Cohort Studies[mh])")
    assert "(english[la] OR portuguese[la])" in q and "humans[mh]" in q and q.endswith("NOT preprint[pt]")
    with pytest.raises(ValueError):
        research.Filters(study_types=["fake"])
    with pytest.raises(ValueError):
        research.Filters(date_from="2026-01-01", date_to="2020-01-01")


def test_document_upload_and_auth(client, auth):
    assert client.post("/documents/extract", headers={"X-Filename": "a.txt"}, content=b"a" * 30).status_code == 401
    r = client.post(
        "/documents/extract", headers={**auth, "X-Filename": "ficha.txt"}, content="Tema: prevenção de quedas em idosos.".encode()
    )
    assert r.status_code == 200 and "idosos" in r.json()["text"] and len(r.json()["sha256"]) == 64
    assert client.post("/documents/extract", headers={**auth, "X-Filename": "ficha.exe"}, content=b"x" * 30).status_code == 422
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Produção científica sobre prevenção de quedas.</w:t></w:r></w:p></w:document>',
        )
    assert "Produção" in research.extract_document(out.getvalue(), "ficha.docx")["text"]


def test_draft_edit_then_freeze(client, auth):
    body = {
        "title": "Pesquisa de teste",
        "protocol": {"question": "Quedas podem ser prevenidas?", "inclusion": ["Idosos"], "exclusion": ["Crianças"]},
    }
    rid = client.post("/reviews", headers=auth, json=body).json()["id"]
    body["title"] = "Protocolo revisado"
    assert client.put(f"/reviews/{rid}/draft", headers=auth, json=body).status_code == 200
    client.post(f"/reviews/{rid}/approve", headers=auth)
    assert client.put(f"/reviews/{rid}/draft", headers=auth, json=body).status_code == 409


def test_search_filter_idempotency(client, auth, review):
    h = {**auth, "Idempotency-Key": "filter-test-01"}
    body = {"query": "exercise", "filters": {"languages": ["english"]}}
    a = client.post(f"/reviews/{review}/searches", headers=h, json=body)
    assert a.status_code == 202
    assert client.post(f"/reviews/{review}/searches", headers=h, json=body).json()["search_id"] == a.json()["search_id"]
    body["filters"]["languages"] = ["portuguese"]
    assert client.post(f"/reviews/{review}/searches", headers=h, json=body).status_code == 409


def test_recommendation_acceptance_is_human_and_no_fulltext_auto(client, auth, review, article):
    with db.Session() as s:
        a = s.get(db.Article, article)
        a.recommendation = {"recommendation": "include", "reason": "Matches protocol", "quote": "Randomized trial"}
        s.commit()
    assert (
        client.post(
            f"/reviews/{review}/recommendations/accept",
            headers=auth,
            json={"article_ids": [article], "reason": "Li e aprovei esta inclusão."},
        ).status_code
        == 200
    )
    detail = client.get("/reviews/" + review, headers=auth).json()
    assert detail["decisions"][0]["stage"] == "title_abstract"
    assert detail["prisma"]["included_reports"] == 0 and any(j["kind"] == "pdf" for j in detail["jobs"])


def test_delivery_claim_ack_and_ambiguous_writes(review):
    with db.Session() as s:
        j = delivery.request_delivery(s, s.get(db.Review, review), "drive", "test-drive-key")
        jid = j.id
        s.commit()
        out = delivery.claim(s)
        s.commit()
        assert out[0]["action"] == "folder"
        assert delivery.claim(s) == []
        delivery.acknowledge(s, jid, {"action": "folder", "remote_id": "folder123"})
        s.commit()
        item = delivery.claim(s)[0]
        s.commit()
        assert item["action"] == "file" and item["cursor"] == 0
        delivery.acknowledge(s, jid, {"action": "file", "remote_id": "file123", "cursor": 0})
        s.commit()
        delivery.claim(s)
        s.commit()
        j = s.get(db.Job, jid)
        j.lease_until = 0
        s.commit()
        assert delivery.claim(s) == []
        s.commit()
        assert s.get(db.Job, jid).status == "needs_reconciliation"
        snap = snapshot(s, s.get(db.Review, review))
        assert "snapshot" not in snap["jobs"][0]["payload"]


def test_history_and_methodology_exports(client, auth, review, article):
    r = client.get(f"/reviews/{review}/export/csv", headers=auth)
    assert r.status_code == 200 and "not browser session CSV" in r.text
    assert client.get(f"/reviews/{review}/export/md", headers=auth).status_code == 200
    z = client.get(f"/reviews/{review}/export/zip", headers=auth)
    assert z.status_code == 200
    with zipfile.ZipFile(io.BytesIO(z.content)) as archive:
        assert "matriz.xlsx" in archive.namelist() and "historico-pubmed.csv" in archive.namelist()
        assert json.loads(archive.read("artigos-pendentes.json")) == []


def test_intake_is_authenticated_deduplicated_and_unapproved(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings(), "automation_owner_id", "00000000-0000-0000-0000-000000000001")
    body = {
        "title": "Pré-inicial via ClickUp",
        "task_id": "qa-intake-001",
        "production_text": "Ficha de produção: prevenção de quedas em idosos.",
    }
    assert client.post("/internal/intake", json=body).status_code == 401
    h = {"X-Internal-Token": settings().internal_token}
    a = client.post("/internal/intake", headers=h, json=body)
    assert a.status_code == 202 and a.json()["created"]
    b = client.post("/internal/intake", headers=h, json=body)
    assert b.json()["review_id"] == a.json()["review_id"] and not b.json()["created"]
    with db.Session() as s:
        r = s.get(db.Review, a.json()["review_id"])
        assert r.approved_at is None and r.protocol["auto_search"]
        assert len(list(s.query(db.Job).filter_by(review_id=r.id))) == 1


def test_approved_auto_search_uses_frozen_filters(client, auth, monkeypatch):
    body = {
        "title": "Fluxo com aprovação",
        "protocol": {
            "question": "Exercício reduz quedas em idosos?",
            "inclusion": ["Idosos"],
            "exclusion": ["Crianças"],
            "auto_search": True,
            "filters": {"languages": ["english"]},
        },
    }
    rid = client.post("/reviews", headers=auth, json=body).json()["id"]
    with db.Session() as s:
        j = db.Job(
            review_id=rid,
            kind="planning",
            request_key="plan-test",
            status="done",
            payload={"result": {"strategies": [{"query": "exercise[tiab] AND falls[tiab]"}]}},
        )
        s.add(j)
        s.commit()
    assert client.post("/reviews/" + rid + "/approve", headers=auth).status_code == 200
    client.post("/reviews/" + rid + "/approve", headers=auth)
    with db.Session() as s:
        searches = list(s.query(db.Search).filter_by(review_id=rid))
        assert len(searches) == 1 and "english[la]" in searches[0].query
        assert searches[0].raw["automatic_screening"] is True


def test_auto_approval_waits_for_strategy(client, auth):
    body = {
        "title": "Auto fluxo incompleto",
        "protocol": {
            "question": "Exercício reduz quedas em idosos?",
            "inclusion": ["Idosos"],
            "exclusion": ["Crianças"],
            "auto_search": True,
        },
    }
    rid = client.post("/reviews", headers=auth, json=body).json()["id"]
    assert client.post("/reviews/" + rid + "/approve", headers=auth).status_code == 409
    assert client.get("/reviews/" + rid, headers=auth).json()["review"]["approved_at"] is None
