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
