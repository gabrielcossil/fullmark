import time, re, hashlib
import xml.etree.ElementTree as ET
import httpx
from .config import settings

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"


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


def search(query, limit):
    s = settings()
    params = {"db": "pubmed", "tool": "fullmark_research", "email": s.ncbi_email}
    if s.ncbi_api_key:
        params["api_key"] = s.ncbi_api_key
    with httpx.Client(timeout=45) as c:
        r = c.get(BASE + "esearch.fcgi", params={**params, "term": query, "retmode": "json", "retmax": limit, "sort": "pub date"})
        r.raise_for_status()
        raw = r.json()
        data = raw["esearchresult"]
        if "ERROR" in raw or data.get("errorlist"):
            raise ValueError("PubMed rejected search")
        ids = data["idlist"]
        records = []
        for i in range(0, len(ids), 100):
            time.sleep(0.35)
            r = c.post(BASE + "efetch.fcgi", data={**params, "id": ",".join(ids[i : i + 100]), "retmode": "xml"})
            r.raise_for_status()
            records.extend(parse(r.text))
        if len(records) != len(ids):
            raise ValueError("PubMed fetch incomplete; retry required")
        return records, raw
