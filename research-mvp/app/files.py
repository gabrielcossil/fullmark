import hashlib, io, re
from pathlib import Path
from urllib.parse import urlparse, urljoin, parse_qs
import httpx
from pypdf import PdfReader
from .config import settings

MAX_PDF = 20 * 1024 * 1024
ALLOWED = {"europepmc.org", "www.ebi.ac.uk", "pmc.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov", "pmc-oa-opendata.s3.amazonaws.com"}


def download_pdf(url):
    with httpx.Client(timeout=25, follow_redirects=False) as c:
        for _ in range(5):
            u = urlparse(url)
            if u.scheme != "https" or u.hostname not in ALLOWED or u.username or u.password or u.port not in (None, 443):
                raise ValueError("PDF URL outside repository allowlist")
            with c.stream("GET", url) as r:
                if r.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, r.headers["location"])
                    continue
                r.raise_for_status()
                chunks = []
                size = 0
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > MAX_PDF:
                        raise ValueError("PDF exceeds 20 MiB")
                    chunks.append(chunk)
                data = b"".join(chunks)
                if not data.startswith(b"%PDF-"):
                    raise ValueError("Repository did not return PDF")
                reader = PdfReader(io.BytesIO(data), strict=True)
                if reader.is_encrypted or len(reader.pages) > 1000:
                    raise ValueError("Unsupported PDF")
                return data, url
    raise ValueError("Too many redirects")


def headers():
    s = settings()
    return {"apikey": s.supabase_secret_key}


def put(path, data, content_type):
    s = settings()
    if s.storage_proxy_url:
        with httpx.Client(timeout=40) as c:
            r = c.post(
                s.storage_proxy_url,
                params={"path": path},
                headers={"X-Storage-Token": s.storage_proxy_token, "Content-Type": content_type},
                content=data,
            )
            r.raise_for_status()
    elif s.supabase_url:
        with httpx.Client(timeout=40) as c:
            r = c.post(
                s.supabase_url + "/storage/v1/object/fullmark-private/" + path,
                headers={**headers(), "Content-Type": content_type, "x-upsert": "true"},
                content=data,
            )
            r.raise_for_status()
    else:
        p = Path(s.local_storage) / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return path


def get(path):
    s = settings()
    if s.storage_proxy_url:
        with httpx.Client(timeout=40) as c:
            r = c.get(s.storage_proxy_url, params={"path": path}, headers={"X-Storage-Token": s.storage_proxy_token})
            r.raise_for_status()
            return r.content
    if s.supabase_url:
        with httpx.Client(timeout=40) as c:
            r = c.get(s.supabase_url + "/storage/v1/object/fullmark-private/" + path, headers=headers())
            r.raise_for_status()
            return r.content
    return (Path(s.local_storage) / path).read_bytes()


def pmc_cloud_pdf(pmcid, pmid):
    import xml.etree.ElementTree as ET

    base = "https://pmc-oa-opendata.s3.amazonaws.com"
    with httpx.Client(timeout=25) as c:
        response = c.get(base + "/", params={"list-type": "2", "prefix": "metadata/" + pmcid + ".", "max-keys": 20})
        response.raise_for_status()
        root = ET.fromstring(response.content)
        ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
        if root.findtext("s:IsTruncated", namespaces=ns) == "true":
            raise ValueError("Too many article versions; human selection required")
        records = []
        for key in root.findall("s:Contents/s:Key", ns):
            if not re.fullmatch(r"metadata/" + pmcid + r"\.\d+\.json", key.text or ""):
                continue
            response = c.get(base + "/" + key.text)
            response.raise_for_status()
            meta = response.json()
            if meta.get("pmcid") != pmcid or str(meta.get("pmid")) != pmid:
                raise ValueError("PMC Cloud identifiers do not match")
            if meta.get("is_retracted"):
                return None, {"reason": "Retracted article; human review required"}
            if not meta.get("is_manuscript") and meta.get("is_pmc_openaccess") and meta.get("pdf_url"):
                records.append(meta)
        if len(records) != 1:
            return None, {"reason": "PMC Cloud version unavailable or ambiguous; human selection required"}
        meta = records[0]
        licence = str(meta.get("license_code", "")).lower().replace(" ", "-").replace("_", "-")
        if not re.fullmatch(r"(cc-by|cc-by-sa|cc0|cc-zero|public-domain)(-\d+(?:\.\d+)?)?", licence):
            return None, {"reason": "PMC Cloud licence requires human review"}
        u = urlparse(meta["pdf_url"])
        if u.scheme == "s3" and u.netloc == "pmc-oa-opendata":
            url = base + u.path + ("?" + u.query if u.query else "")
        elif u.scheme == "https" and u.hostname == "pmc-oa-opendata.s3.amazonaws.com":
            url = meta["pdf_url"]
        else:
            raise ValueError("Unexpected PMC Cloud object location")
        if not u.path.startswith("/" + pmcid + "."):
            raise ValueError("PMC Cloud PDF prefix mismatch")
        return url, meta


def retrieve(article, owner_id):
    pmid = article.metadata_json.get("pmid", "")
    if not re.fullmatch(r"\d+", pmid):
        return {"status": "unavailable", "reason": "No PubMed identifier; human legal retrieval required"}
    # The legacy PMC OA Web Service was retired in August 2026.
    # Europe PMC core metadata identifies the article, explicit licence and OA PDF rendition.
    with httpx.Client(timeout=25) as c:
        r = c.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": "EXT_ID:" + pmid + " AND SRC:MED", "format": "json", "resultType": "core"},
        )
        r.raise_for_status()
        raw = r.json()
    results = raw.get("resultList", {}).get("result", [])
    record = next((x for x in results if x.get("id") == pmid and x.get("source") == "MED"), None)
    if not record or record.get("isOpenAccess") != "Y" or not record.get("license"):
        return {"status": "unavailable", "reason": "Europe PMC does not confirm an explicitly licensed OA copy"}
    expected = article.metadata_json.get("pmcid", "")
    if expected and record.get("pmcid") != expected:
        raise ValueError("Repository PMCID does not match PubMed record")
    license = record["license"].strip().lower().replace(" ", "-")
    if not re.fullmatch(r"(cc-by|cc-by-sa|cc0|cc-zero|public-domain)(-\d+(?:\.\d+)?)?", license):
        return {"status": "unavailable", "reason": "Licence requires human permission review: " + record["license"]}
    pmcid = record.get("pmcid", "")
    if not re.fullmatch(r"PMC\d+", pmcid):
        return {"status": "unavailable", "reason": "No PMC Cloud identifier"}
    url, cloud_meta = pmc_cloud_pdf(pmcid, pmid)
    if not url:
        return {"status": "unavailable", **cloud_meta}
    data, final = download_pdf(url)
    expected_md5 = parse_qs(urlparse(url).query).get("md5", [""])[0]
    if expected_md5 and hashlib.md5(data, usedforsecurity=False).hexdigest() != expected_md5:
        raise ValueError("PMC Cloud PDF checksum mismatch")
    digest = hashlib.sha256(data).hexdigest()
    path = put(f"{owner_id}/{article.review_id}/pdf/{article.id}/{digest}.pdf", data, "application/pdf")
    reader = PdfReader(io.BytesIO(data))
    pages = [p.extract_text() or "" for p in reader.pages]
    text_path = put(
        f"{owner_id}/{article.review_id}/text/{article.id}/{digest}.json", __import__("json").dumps(pages).encode(), "application/json"
    )
    return {
        "status": "available",
        "path": path,
        "text_path": text_path,
        "sha256": digest,
        "license": record["license"],
        "license_evidence": record,
        "pmc_cloud_metadata": cloud_meta,
        "metadata_source": str(r.url),
        "source_url": final,
        "retrieved_at": __import__("time").time(),
        "pages": len(pages),
    }
