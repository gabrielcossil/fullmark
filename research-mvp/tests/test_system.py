import io, json, zipfile
import pytest, respx, httpx
from sqlalchemy import select
from app import db, main, worker, browser, files, pubmed
from app.config import settings
from app.schemas import BrowserOutput


def test_unauthenticated_denied(client):
    assert client.get("/reviews").status_code == 401
    assert client.post("/internal/tick").status_code == 401


def test_no_owner_bypass(client, review, auth):
    with db.Session() as s:
        r = s.get(db.Review, review)
        r.owner_id = "someone-else"
        s.commit()
    assert client.get("/reviews/" + review, headers=auth).status_code == 404
    assert client.post("/reviews/" + review + "/approve", headers=auth).status_code == 404


def test_protocol_gate(client, auth):
    r = client.post(
        "/reviews",
        headers=auth,
        json={
            "title": "Teste",
            "protocol": {"question": "Qual a eficácia desta intervenção?", "inclusion": ["RCT"], "exclusion": ["Animais"]},
        },
    ).json()["id"]
    assert (
        client.post("/reviews/" + r + "/searches", headers={**auth, "Idempotency-Key": "test-key"}, json={"query": "exercise"}).status_code
        == 409
    )


def test_search_idempotency(client, auth, review):
    path = f"/reviews/{review}/searches"
    h = {**auth, "Idempotency-Key": "test-key"}
    a = client.post(path, headers=h, json={"query": "exercise"})
    b = client.post(path, headers=h, json={"query": "exercise"})
    assert a.status_code == b.status_code == 202
    assert a.json()["search_id"] == b.json()["search_id"]
    assert client.post(path, headers=h, json={"query": "cancer"}).status_code == 409
    assert (
        client.post(path, headers={**auth, "Idempotency-Key": "over-limit"}, json={"query": "exercise", "max_records": 201}).status_code
        == 422
    )


def test_pubmed_dedup_preserves_sources(client, auth, review, monkeypatch):
    records = [{"pmid": "2", "doi": "10.1/example", "title": "Example", "abstract": "Randomized trial"}]
    monkeypatch.setattr(
        pubmed, "search", lambda q, n: (records, {"esearchresult": {"count": "20", "querytranslation": "exercise[All Fields]"}})
    )
    for key in ["search-01", "search-02"]:
        client.post(f"/reviews/{review}/searches", headers={**auth, "Idempotency-Key": key}, json={"query": "exercise"})
        assert worker.tick()
    p = client.get(f"/reviews/{review}/prisma", headers=auth).json()
    assert p["identified"] == 2 and p["duplicates_removed"] == 1 and p["title_abstract_pending"] == 1


def test_two_stage_decisions_and_prisma(client, auth, review, article):
    path = f"/reviews/{review}/articles/{article}/decisions"
    assert (
        client.post(path, headers=auth, json={"stage": "full_text", "verdict": "include", "reason": "Adequado aos critérios"}).status_code
        == 409
    )
    assert (
        client.post(
            path, headers=auth, json={"stage": "title_abstract", "verdict": "include", "reason": "População e desenho elegíveis"}
        ).status_code
        == 200
    )
    assert (
        client.post(path, headers=auth, json={"stage": "full_text", "verdict": "include", "reason": "Adequado aos critérios"}).status_code
        == 409
    )
    assert (
        client.post(
            path, headers=auth, json={"stage": "full_text", "verdict": "not_retrieved", "reason": "PDF indisponível legalmente"}
        ).status_code
        == 200
    )
    p = client.get(f"/reviews/{review}/prisma", headers=auth).json()
    assert p["reports_not_retrieved"] == 1 and p["included_reports"] == 0
    assert (
        client.post(
            path, headers=auth, json={"stage": "title_abstract", "verdict": "exclude", "reason": "Alterar etapa passada"}
        ).status_code
        == 409
    )


def test_decision_history_not_overwritten(client, auth, review, article):
    path = f"/reviews/{review}/articles/{article}/decisions"
    for verdict in ("uncertain", "exclude"):
        assert (
            client.post(
                path, headers=auth, json={"stage": "title_abstract", "verdict": verdict, "reason": "Revisão dos critérios"}
            ).status_code
            == 200
        )
    snap = client.get("/reviews/" + review, headers=auth).json()
    assert len(snap["decisions"]) == 2
    assert snap["prisma"]["title_abstract_excluded"] == 1
    assert snap["prisma"]["complete"]


def test_exports_are_valid_and_formula_safe(client, auth, review, article):
    with db.Session() as s:
        a = s.get(db.Article, article)
        a.metadata_json = {**a.metadata_json, "title": '=HYPERLINK("https://bad.test")'}
        s.commit()
    r = client.get(f"/reviews/{review}/export/xlsx", headers=auth)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    import xml.etree.ElementTree as ET

    for p in z.namelist():
        ET.fromstring(z.read(p))
    xml = z.read("xl/worksheets/sheet2.xml").decode()
    assert "<f>" not in xml and "=HYPERLINK" in xml
    assert len([x for x in z.namelist() if x.startswith("xl/worksheets/")]) == 5
    svg = client.get(f"/reviews/{review}/export/svg", headers=auth)
    ET.fromstring(svg.content)
    assert "PARCIAL" in svg.text


def test_extraction_must_quote_actual_page(client, auth, review, article, monkeypatch):
    with db.Session() as s:
        a = s.get(db.Article, article)
        a.pdf = {"status": "available", "text_path": "test.json"}
        s.commit()
    monkeypatch.setattr(files, "get", lambda path: json.dumps(["Sample size was 120 participants."]).encode())
    path = f"/reviews/{review}/articles/{article}/extraction"
    item = {"field": "n", "value": "120", "page": 1, "quote": "Sample size was 120 participants."}
    assert client.post(path, headers=auth, json={"items": [item]}).status_code == 200
    item["quote"] = "Invented sample size 200"
    assert client.post(path, headers=auth, json={"items": [item]}).status_code == 422


def test_identity_normalization():
    assert pubmed.identity({"doi": "https://doi.org/10.10/ABC "}) == "doi:10.10/abc"
    assert pubmed.identity({"pmid": "42"}) == "pmid:42"


def test_parser_structured_abstract():
    xml = '<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>42</PMID><Article><ArticleTitle>Mixed <i>title</i></ArticleTitle><Abstract><AbstractText Label="RESULTS">Evidence <b>found</b>.</AbstractText></Abstract></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1/a</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'
    a = pubmed.parse(xml)[0]
    assert a["title"] == "Mixed title" and a["abstract"] == "RESULTS: Evidence found."


@respx.mock
def test_browser_v4_contract(monkeypatch):
    monkeypatch.setattr(settings(), "browser_use_api_key", "test-browser-key")
    monkeypatch.setattr(settings(), "browser_network_policy_id", "policy-test")
    route = respx.post(browser.BASE + "/runs").mock(return_value=httpx.Response(200, json={"id": "external-1"}))
    assert browser.submit({"question": "test"}, []) == "external-1"
    body = json.loads(route.calls.last.request.content)
    assert "outputSchema" in body and body["agentmail"] is False and body["browserSettings"]["networkPolicyId"] == "policy-test"
    assert route.calls.last.request.headers["X-Browser-Use-API-Key"] == "test-browser-key"
    respx.get(browser.BASE + "/runs/external-1/status").mock(return_value=httpx.Response(200, json={"status": "completed"}))
    respx.get(browser.BASE + "/runs/external-1").mock(return_value=httpx.Response(200, json={"output": {"findings": [], "sources": []}}))
    assert browser.poll("external-1")[0].findings == []


def test_browser_ambiguous_submission_never_repeated(review, article, monkeypatch):
    def fail(*a):
        raise httpx.ReadTimeout("ambiguous")

    monkeypatch.setattr(browser, "submit", fail)
    with db.Session() as s:
        j = db.enqueue(s, review, "browser", "browser-unknown", {})
        jid = j.id
        s.commit()
    worker.tick()
    with db.Session() as s:
        assert s.get(db.Job, jid).status == "needs_reconciliation"
    assert not worker.tick()


def test_browser_fabricated_quote_rejected(review, article, monkeypatch):
    output = BrowserOutput.model_validate(
        {
            "findings": [{"article_id": article, "recommendation": "include", "reason": "Looks eligible", "quote": "Invented quote"}],
            "sources": [],
        }
    )
    monkeypatch.setattr(browser, "poll", lambda run: (output, {"model": "test"}))
    with db.Session() as s:
        j = db.enqueue(s, review, "browser", "browser-quote", {"article_ids": [article]})
        j.external_id = "run-quote"
        jid = j.id
        s.commit()
    worker.tick()
    with db.Session() as s:
        assert not s.get(db.Article, article).recommendation
        assert s.get(db.Job, jid).attempts == 1


def test_browser_success_is_only_recommendation(client, auth, review, article, monkeypatch):
    output = BrowserOutput.model_validate(
        {
            "findings": [
                {"article_id": article, "recommendation": "include", "reason": "Eligible trial", "quote": "Randomized trial of exercise."}
            ],
            "sources": ["https://pubmed.ncbi.nlm.nih.gov/1/"],
        }
    )
    monkeypatch.setattr(browser, "poll", lambda run: (output, {"model": "test"}))
    with db.Session() as s:
        j = db.enqueue(s, review, "browser", "browser-valid", {"article_ids": [article]})
        j.external_id = "run-valid"
        s.commit()
    worker.tick()
    snap = client.get("/reviews/" + review, headers=auth).json()
    assert snap["articles"][0]["recommendation"]["recommendation"] == "include"
    assert snap["decisions"] == [] and snap["prisma"]["title_abstract_pending"] == 1


@respx.mock
def test_pdf_redirect_cannot_reach_private_host():
    respx.get("https://europepmc.org/a.pdf").mock(
        return_value=httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})
    )
    with pytest.raises(ValueError, match="allowlist"):
        files.download_pdf("https://europepmc.org/a.pdf")


@respx.mock
def test_html_masquerading_as_pdf_rejected():
    respx.get("https://europepmc.org/a.pdf").mock(return_value=httpx.Response(200, content=b"<html>blocked</html>"))
    with pytest.raises(ValueError, match="did not return PDF"):
        files.download_pdf("https://europepmc.org/a.pdf")


def test_pdf_no_pmid_does_not_download(review, article):
    with db.Session() as s:
        a = s.get(db.Article, article)
        a.metadata_json = {}
        assert files.retrieve(a, "user")["status"] == "unavailable"


def test_failed_job_bounded_retry(review, monkeypatch):
    monkeypatch.setattr(pubmed, "search", lambda *a: (_ for _ in ()).throw(RuntimeError("do not log secret")))
    with db.Session() as s:
        search = db.Search(review_id=review, request_key="failure-search", query="example", max_records=1)
        s.add(search)
        s.flush()
        j = db.enqueue(s, review, "pubmed", "failed-job", {"search_id": search.id})
        jid = j.id
        s.commit()
    for _ in range(3):
        assert worker.tick()
        with db.Session() as s:
            j = s.get(db.Job, jid)
            j.available_at = 0
            s.commit()
    with db.Session() as s:
        j = s.get(db.Job, jid)
        assert j.status == "failed" and j.error == "RuntimeError"
    assert not worker.tick()


def test_security_headers(client):
    r = client.get("/")
    assert r.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_production_refuses_demo(monkeypatch):
    from app.config import settings as get_settings

    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_retry_requires_failed_owned_job(client, auth, review):
    with db.Session() as s:
        j = db.enqueue(s, review, "pdf", "retry-id", {"article_id": "irrelevant"})
        j.status = "failed"
        j.attempts = 3
        jid = j.id
        s.commit()
    path = f"/reviews/{review}/jobs/{jid}/retry"
    assert client.post(path, headers=auth).status_code == 202
    assert client.post(path, headers=auth).status_code == 409


def test_full_text_available_is_not_assessed(client, auth, review, article):
    client.post(
        f"/reviews/{review}/articles/{article}/decisions",
        headers=auth,
        json={"stage": "title_abstract", "verdict": "include", "reason": "Atende critérios iniciais"},
    )
    with db.Session() as s:
        a = s.get(db.Article, article)
        a.pdf = {"status": "available"}
        s.commit()
    p = client.get(f"/reviews/{review}/prisma", headers=auth).json()
    assert p["reports_available"] == 1 and p["reports_assessed"] == 0 and p["full_text_pending"] == 1


@respx.mock
def test_live_auth_is_validated_not_jwt_decoded(client, monkeypatch):
    monkeypatch.setattr(settings(), "demo_mode", False)
    monkeypatch.setattr(settings(), "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings(), "supabase_publishable_key", "test-public-key")
    respx.get("https://project.supabase.co/auth/v1/user").mock(return_value=httpx.Response(401, json={"error": "invalid"}))
    assert client.get("/reviews", headers={"Authorization": "Bearer forged.jwt.token"}).status_code == 401


@respx.mock
def test_private_pdf_uploaded_to_storage(monkeypatch):
    monkeypatch.setattr(settings(), "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings(), "supabase_secret_key", "server-only-test-secret")
    route = respx.post("https://project.supabase.co/storage/v1/object/fullmark-private/owner/review/a.pdf").mock(
        return_value=httpx.Response(200, json={"Key": "a.pdf"})
    )
    assert files.put("owner/review/a.pdf", b"%PDF-1.7", "application/pdf") == "owner/review/a.pdf"
    assert route.calls.last.request.headers["apikey"] == "server-only-test-secret"
    assert route.calls.last.request.headers["x-upsert"] == "true"


def test_parser_does_not_confuse_reference_ids():
    xml = '<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>42</PMID><Article><ArticleTitle>Actual paper</ArticleTitle></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="pmc">PMC42</ArticleId><ArticleId IdType="doi">10.1/actual</ArticleId></ArticleIdList><ReferenceList><Reference><ArticleIdList><ArticleId IdType="pmc">PMC99</ArticleId><ArticleId IdType="doi">10.1/cited</ArticleId></ArticleIdList></Reference></ReferenceList></PubmedData></PubmedArticle></PubmedArticleSet>'
    a = pubmed.parse(xml)[0]
    assert a["pmcid"] == "PMC42" and a["doi"] == "10.1/actual"


@respx.mock
def test_noncommercial_license_requires_human_permission(review, article):
    respx.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search").mock(
        return_value=httpx.Response(
            200,
            json={"resultList": {"result": [{"id": "1", "source": "MED", "pmcid": "PMC1", "isOpenAccess": "Y", "license": "cc by-nc"}]}},
        )
    )
    with db.Session() as s:
        r = files.retrieve(s.get(db.Article, article), "user")
        assert r["status"] == "unavailable" and "permission review" in r["reason"]


@respx.mock
def test_cloud_pdf_metadata_binding():
    base = "https://pmc-oa-opendata.s3.amazonaws.com"
    listing = '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated><Contents><Key>metadata/PMC1.1.json</Key></Contents></ListBucketResult>'
    respx.get(base + "/").mock(return_value=httpx.Response(200, text=listing))
    meta = {
        "pmcid": "PMC1",
        "pmid": 1,
        "is_retracted": False,
        "is_manuscript": False,
        "is_pmc_openaccess": True,
        "license_code": "CC BY",
        "pdf_url": "s3://pmc-oa-opendata/PMC1.1/PMC1.1.pdf?md5=abc",
    }
    route = respx.get(base + "/metadata/PMC1.1.json").mock(return_value=httpx.Response(200, json=meta))
    url, record = files.pmc_cloud_pdf("PMC1", "1")
    assert url == base + "/PMC1.1/PMC1.1.pdf?md5=abc" and record["license_code"] == "CC BY"
    route.mock(return_value=httpx.Response(200, json={**meta, "pmid": 2}))
    with pytest.raises(ValueError, match="identifiers"):
        files.pmc_cloud_pdf("PMC1", "1")


@respx.mock
def test_retracted_cloud_paper_needs_human_review():
    base = "https://pmc-oa-opendata.s3.amazonaws.com"
    respx.get(base + "/").mock(
        return_value=httpx.Response(
            200,
            text='<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Contents><Key>metadata/PMC1.1.json</Key></Contents></ListBucketResult>',
        )
    )
    respx.get(base + "/metadata/PMC1.1.json").mock(
        return_value=httpx.Response(200, json={"pmcid": "PMC1", "pmid": 1, "is_retracted": True})
    )
    url, record = files.pmc_cloud_pdf("PMC1", "1")
    assert url is None and "Retracted" in record["reason"]


def test_setup_mode_is_closed_to_research_routes():
    from app.setup import app as setup_app
    from fastapi.testclient import TestClient

    with TestClient(setup_app) as c:
        assert c.get("/health/live").json()["ready"] is False
        assert c.get("/health/ready").status_code == 503
        assert c.get("/reviews").status_code == 404
        assert c.post("/internal/tick").status_code == 404


@respx.mock
def test_storage_proxy_keeps_supabase_secret_out_of_render_requests(monkeypatch):
    monkeypatch.setattr(settings(), "storage_proxy_url", "https://project.supabase.co/functions/v1/fullmark-storage")
    monkeypatch.setattr(settings(), "storage_proxy_token", "server-only-storage-capability-token")
    monkeypatch.setattr(settings(), "supabase_secret_key", "must-not-leave-supabase-in-proxy-mode")
    route = respx.post("https://project.supabase.co/functions/v1/fullmark-storage").mock(
        return_value=httpx.Response(200, json={"Key": "test.json"})
    )
    files.put("owner/review/test.json", b"[]", "application/json")
    request = route.calls.last.request
    assert request.headers["X-Storage-Token"] == "server-only-storage-capability-token"
    assert "apikey" not in request.headers and "Authorization" not in request.headers
    respx.get("https://project.supabase.co/functions/v1/fullmark-storage").mock(return_value=httpx.Response(200, content=b"[]"))
    assert files.get("owner/review/test.json") == b"[]"


@respx.mock
def test_invited_user_sets_only_own_password(client, monkeypatch):
    monkeypatch.setattr(settings(), "demo_mode", False)
    monkeypatch.setattr(settings(), "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings(), "supabase_publishable_key", "test-public-key")
    respx.get("https://project.supabase.co/auth/v1/user").mock(
        return_value=httpx.Response(200, json={"id": "invited-user", "email": "reviewer@example.test"})
    )
    route = respx.put("https://project.supabase.co/auth/v1/user").mock(return_value=httpx.Response(200, json={"id": "invited-user"}))
    h = {"Authorization": "Bearer invite-session-test"}
    assert client.get("/auth/me", headers=h).json()["email"] == "reviewer@example.test"
    assert client.post("/auth/password", headers=h, json={"password": "short"}).status_code == 422
    assert client.post("/auth/password", headers=h, json={"password": "new-test-password-12345"}).status_code == 200
    assert route.calls.last.request.headers["Authorization"] == "Bearer invite-session-test"
    assert json.loads(route.calls.last.request.content) == {"password": "new-test-password-12345"}
    assert client.post("/auth/password", json={"password": "new-test-password-12345"}).status_code == 401


@respx.mock
def test_verified_email_allowlist_blocks_other_valid_accounts(client, monkeypatch):
    monkeypatch.setattr(settings(), "demo_mode", False)
    monkeypatch.setattr(settings(), "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings(), "supabase_publishable_key", "public-test")
    monkeypatch.setattr(settings(), "allowed_emails", "reviewer@example.test")
    route = respx.get("https://project.supabase.co/auth/v1/user")
    h = {"Authorization": "Bearer valid-but-not-authorized-user"}
    route.mock(
        return_value=httpx.Response(
            200, json={"id": "other", "email": "outside@example.test", "email_confirmed_at": "2026-11-09T00:00:00Z"}
        )
    )
    assert client.get("/reviews", headers=h).status_code == 403
    route.mock(return_value=httpx.Response(200, json={"id": "reviewer", "email": "reviewer@example.test", "email_confirmed_at": None}))
    assert client.get("/reviews", headers=h).status_code == 403
    route.mock(
        return_value=httpx.Response(
            200, json={"id": "reviewer", "email": "reviewer@example.test", "email_confirmed_at": "2026-11-09T00:00:00Z"}
        )
    )
    assert client.get("/reviews", headers=h).status_code == 200
