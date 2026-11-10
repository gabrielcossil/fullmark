import io
from zipfile import ZipFile
from app import db, writing, worker, browser
from app.schemas import DecisionCreate
from app.service import decide


def source(review):
    with db.Session() as s:
        r = s.get(db.Review, review)
        a = db.Article(
            review_id=review,
            identity="pmid:123",
            metadata_json={"title": "Evidence fixture", "pmid": "123", "abstract": "Exercise was studied."},
            pdf={},
        )
        s.add(a)
        s.flush()
        decide(s, r, a, DecisionCreate(stage="title_abstract", verdict="include", reason="Matches eligibility"), r.owner_id)
        s.commit()
        return a.id


def test_writing_revisions_comments_word(client, auth, review):
    source(review)
    url = f"/reviews/{review}/writing"
    initial = client.get(url, headers=auth).json()
    body = {
        "revision": initial["revision"],
        "title": "Prévia de teste",
        "client": "Equipe QA",
        "content": "# Introdução\nTexto fundamentado [PMID: 123].",
    }
    saved = client.put(url, headers=auth, json=body).json()
    assert saved["revision"] and len(saved["sources"]) == 1
    assert not saved["sources"][0]["full_text_reviewed"]
    assert client.put(url, headers=auth, json=body).status_code == 409
    c = client.post(url + "/comments", headers=auth, json={"text": "Rever redação", "anchor": "Texto fundamentado"}).json()["comments"][0]
    word = client.get(url + "/docx", headers=auth)
    assert word.status_code == 200
    with ZipFile(io.BytesIO(word.content)) as z:
        text = z.read("word/document.xml").decode()
        assert "Introdução" in text and "Rever redação" in text and "123" in text
    resolved = client.post(url + f"/comments/{c['id']}/resolve", headers=auth).json()
    assert resolved["comments"][0]["resolved"]
    with db.Session() as s:
        assert not any(d.stage == "full_text" for d in s.query(db.Decision).all())


def test_writing_owner_and_prepare_idempotent(client, auth, review):
    source(review)
    with db.Session() as s:
        r = s.get(db.Review, review)
        r.owner_id = "another-owner"
        s.commit()
    assert client.get(f"/reviews/{review}/writing", headers=auth).status_code == 404
    assert client.put(f"/reviews/{review}/writing", headers=auth, json={"title": "Unauthorized"}).status_code == 404
    with db.Session() as s:
        r = s.get(db.Review, review)
        r.owner_id = "00000000-0000-0000-0000-000000000001"
        s.commit()
    for _ in range(2):
        assert client.post(f"/reviews/{review}/prepare-delivery", headers=auth).status_code == 200
    with db.Session() as s:
        assert s.query(db.Job).filter_by(kind="pdf").count() == 1


def test_writing_proposal_never_overwrites_document(client, auth, review, monkeypatch):
    source(review)
    with db.Session() as s:
        r = s.get(db.Review, review)
        writing.save(s, r, r.owner_id, writing.DraftSave(title="Título de teste", content="Texto humano"))
        writing.request(s, r, r.owner_id, writing.WritingRequest(mode="draft"))
        j = s.query(db.Job).filter_by(kind="writing").one()
        j.external_id = "existing"
        j.status = "running"
        s.commit()
        jid = j.id
    monkeypatch.setattr(
        browser, "poll", lambda *a, **k: (writing.WritingOutput(content="# Introdução\nProposta [PMID: 123]."), {"totalCostUsd": 0.01})
    )
    with db.Session() as s:
        j = s.get(db.Job, jid)
        worker.handle(s, j)
        s.commit()
        assert j.payload["result"]["content"].startswith("# Introdução")
        assert writing.state(s, s.get(db.Review, review))["draft"]["content"] == "Texto humano"
    monkeypatch.setattr(browser, "poll", lambda *a, **k: (writing.WritingOutput(content="Inventado (PMID: 999)."), {}))
    with db.Session() as s:
        import pytest

        with pytest.raises(ValueError):
            worker.handle(s, s.get(db.Job, jid))


def test_uploaded_pdf_requires_accepted_owned_article(client, auth, review, monkeypatch):
    from app import files

    aid = source(review)
    assert client.post(f"/reviews/{review}/articles/{aid}/pdf", headers=auth, content=b"not a PDF").status_code == 422
    stored = {}
    monkeypatch.setattr(files, "put", lambda path, data, mime: stored.setdefault(path, path))
    from pypdf import PdfWriter

    out = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(out)
    uploaded = client.post(f"/reviews/{review}/articles/{aid}/pdf", headers=auth, content=out.getvalue())
    assert uploaded.status_code == 200
    assert len(stored) == 2
    assert client.post(f"/reviews/{review}/articles/{aid}/pdf", headers=auth, content=out.getvalue()).status_code == 409


def test_independent_previews_workflow_and_approval(client, auth, review):
    source(review)
    created = [
        client.post(f"/reviews/{review}/writing-projects", headers=auth, json={"title": f"Prévia independente {i}"}).json()["draft_id"]
        for i in range(2)
    ]
    a = f"/reviews/{review}/writing?draft_id={created[0]}"
    b = f"/reviews/{review}/writing?draft_id={created[1]}"
    first = client.get(a, headers=auth).json()
    data = {
        "revision": first["revision"],
        "title": "Primeira prévia",
        "content": "Texto para revisar",
        "layout": {"font": "Times New Roman", "size": 12, "top": 3, "bottom": 2, "left": 3, "right": 2, "pages": 10, "spacing": 1.5},
        "identity": {"client_name": "Pessoa QA", "city": "Cidade QA"},
    }
    assert client.put(a, headers=auth, json=data).status_code == 200
    assert client.get(b, headers=auth).json()["draft"]["content"] == ""
    workflow = f"/reviews/{review}/writing/workflow?draft_id={created[0]}"
    assert client.post(workflow, headers=auth, json={"status": "final_started"}).status_code == 409
    comment = client.post(
        f"/reviews/{review}/writing/comments?draft_id={created[0]}", headers=auth, json={"text": "Ajustar trecho", "anchor": "Texto"}
    ).json()["comments"][0]
    assert client.get(b, headers=auth).json()["comments"] == []
    assert client.post(workflow, headers=auth, json={"status": "approved"}).status_code == 409
    client.post(f"/reviews/{review}/writing/comments/{comment['id']}/resolve?draft_id={created[0]}", headers=auth)
    assert client.post(workflow, headers=auth, json={"status": "approved"}).status_code == 200
    updated = client.get(a, headers=auth).json()
    data["revision"] = updated["revision"]
    assert client.put(a, headers=auth, json=data).status_code == 409
    assert client.post(workflow, headers=auth, json={"status": "final_started"}).status_code == 200
    assert (
        client.post(workflow, headers=auth, json={"status": "changes_requested", "note": "Reabrir para corrigir objetivos"}).status_code
        == 200
    )
    assert client.put(a, headers=auth, json=data).status_code == 200


def test_template_rich_word_and_layout(client, auth, review):
    from docx import Document
    import base64

    template = Document()
    template.add_paragraph("{{nome}}")
    template.add_paragraph("{{titulo}}")
    out = io.BytesIO()
    template.save(out)
    assert writing.validate_template(out.getvalue())
    rich = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Trecho em negrito", "marks": [{"type": "bold"}, {"type": "highlight"}]}],
            }
        ],
    }
    body = {
        "title": "Título formatado",
        "content": "Trecho em negrito",
        "rich": rich,
        "identity": {"client_name": "Pessoa QA"},
        "layout": {"left": 3, "right": 2, "top": 3, "bottom": 2, "font": "Arial", "size": 12, "spacing": 1.5, "pages": 5},
        "template_docx": base64.b64encode(out.getvalue()).decode(),
    }
    assert client.put(f"/reviews/{review}/writing", headers=auth, json=body).status_code == 200
    word = client.get(f"/reviews/{review}/writing/docx", headers=auth)
    doc = Document(io.BytesIO(word.content))
    assert doc.paragraphs[0].text == "Pessoa QA"
    assert doc.paragraphs[1].text == "Título formatado"
    assert any(r.bold for p in doc.paragraphs for r in p.runs)
    assert abs(doc.sections[0].left_margin.cm - 3) < 0.01
    body["revision"] = client.get(f"/reviews/{review}/writing", headers=auth).json()["revision"]
    body["layout"]["left"] = 99
    assert client.put(f"/reviews/{review}/writing", headers=auth, json=body).status_code == 422


def test_project_owner_and_notifications(client, auth, review):
    source(review)
    project = client.post(f"/reviews/{review}/writing-projects", headers=auth, json={"title": "QA privada"}).json()["draft_id"]
    with db.Session() as s:
        j = db.Job(
            review_id=review, kind="writing", request_key="notify-test", payload={"draft_id": project, "mode": "draft"}, status="done"
        )
        s.add(j)
        s.commit()
        jid = j.id
    notifications = client.get("/notifications", headers=auth).json()
    assert notifications[0]["draft_id"] == project and not notifications[0]["read"]
    client.post(f"/reviews/{review}/notifications/{jid}/read", headers=auth)
    assert client.get("/notifications", headers=auth).json()[0]["read"]
    with db.Session() as s:
        r = s.get(db.Review, review)
        r.owner_id = "another"
        s.commit()
    assert client.get("/writing-projects", headers=auth).json() == []
    assert client.get("/notifications", headers=auth).json() == []
    assert client.get(f"/reviews/{review}/writing?draft_id={project}", headers=auth).status_code == 404
