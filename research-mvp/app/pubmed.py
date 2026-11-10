import time, re, hashlib, threading
import xml.etree.ElementTree as ET
import httpx
from .config import settings

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
_rate_lock = threading.Lock()
_next_request = 0.0


def request(client, method, *args, **kwargs):
    global _next_request
    with _rate_lock:
        time.sleep(max(0, _next_request - time.monotonic()))
        _next_request = time.monotonic() + 0.36
    return getattr(client, method)(*args, **kwargs)


def text(node):
    return "".join(node.itertext()).strip() if node is not None else ""


def identity(a):
    doi = re.sub(r"^https?://(?:dx\.)?doi.org/|^doi:\s*", "", a.get("doi", "").strip(), flags=re.I).lower().strip()
    if doi:
        return "doi:" + doi
    if a.get("pmid"):
        return "pmid:" + str(a["pmid"])
    # Missing identifiers are never deduplicated by title alone.
    return "source:" + hashlib.sha256(str(a).encode()).hexdigest()


def parse(xml):
    root = ET.fromstring(xml)
    result = []
    for node in root.findall(".//PubmedArticle"):
        c = node.find("MedlineCitation")
        article = c.find("Article")
        ids = {n.get("IdType"): text(n) for n in node.findall("PubmedData/ArticleIdList/ArticleId")}
        result.append(
            dict(
                pmid=text(c.find("PMID")),
                doi=ids.get("doi", ""),
                pmcid=ids.get("pmc", ""),
                title=text(article.find("ArticleTitle")),
                abstract="\n".join(
                    (n.get("Label", "") + ": " if n.get("Label") else "") + text(n) for n in article.findall(".//AbstractText")
                ),
                journal=text(article.find("Journal/Title")),
                year=text(article.find(".//PubDate/Year")),
                authors=[text(n.find("LastName")) + " " + text(n.find("ForeName")) for n in article.findall("AuthorList/Author")],
                publication_types=[text(n) for n in article.findall("PublicationTypeList/PublicationType")],
                source="PubMed",
                url="https://pubmed.ncbi.nlm.nih.gov/" + text(c.find("PMID")) + "/",
                raw_xml=ET.tostring(node, encoding="unicode"),
            )
        )
    return result


def search(query, limit, progress=None, sort="pub date"):
    s = settings()
    params = {"db": "pubmed", "tool": "fullmark_research", "email": s.ncbi_email}
    if s.ncbi_api_key:
        params["api_key"] = s.ncbi_api_key
    with httpx.Client(timeout=45) as c:
        r = request(
            c,
            "get",
            BASE + "esearch.fcgi",
            params={**params, "term": query, "retmode": "json", "retmax": limit, "sort": sort, "usehistory": "y"},
        )
        r.raise_for_status()
        raw = r.json()
        data = raw["esearchresult"]
        if "ERROR" in raw or data.get("errorlist"):
            raise ValueError("PubMed rejected search")
        ids = data["idlist"]
        if progress:
            progress({"stage": "fetching", "found": int(data["count"]), "fetched": 0, "target": len(ids)})
        records = []
        for i in range(0, len(ids), 25):
            time.sleep(0.35)
            r = request(c, "post", BASE + "efetch.fcgi", data={**params, "id": ",".join(ids[i : i + 25]), "retmode": "xml"})
            r.raise_for_status()
            records.extend(parse(r.text))
            if progress:
                progress({"stage": "fetching", "found": int(data["count"]), "fetched": len(records), "target": len(ids)})
        if len(records) != len(ids):
            raise ValueError("PubMed fetch incomplete; retry required")
        return records, raw


def verify_mesh(term):
    """Never label model-invented headings as verified MeSH."""
    if not re.fullmatch(r"[A-Za-z0-9 ,()'\-/]{2,180}", term):
        return {"term": term, "verified": False, "reason": "Invalid heading format"}
    with httpx.Client(timeout=25) as c:
        r = request(
            c,
            "get",
            BASE + "esearch.fcgi",
            params={
                "db": "mesh",
                "term": '"' + term + '"[MeSH Terms]',
                "retmode": "json",
                "retmax": 1,
                "tool": "fullmark_research",
                "email": settings().ncbi_email,
            },
        )
        r.raise_for_status()
        result = r.json()["esearchresult"]
        ids = result.get("idlist", [])
        if not ids:
            return {"term": term, "verified": False, "reason": "Not found in MeSH"}
        time.sleep(0.35)
        r = request(c, "get", BASE + "esummary.fcgi", params={"db": "mesh", "id": ids[0], "retmode": "json"})
        r.raise_for_status()
        data = r.json()["result"][ids[0]]
    heading = data.get("ds_meshterms", [])
    exact = any(x.casefold() == term.casefold() for x in heading)
    return {"term": term, "verified": exact, "uid": ids[0], "heading": heading, "source": "https://www.ncbi.nlm.nih.gov/mesh/" + ids[0]}
