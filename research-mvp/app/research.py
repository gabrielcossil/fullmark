"""Validated PubMed query builder and bounded production-sheet extraction."""

import io, zipfile, hashlib, re
import xml.etree.ElementTree as ET
from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator
from pypdf import PdfReader

PUBLICATION_TYPES = {
    "randomized": ("Ensaio clínico randomizado", "Randomized Controlled Trial[pt]"),
    "clinical": ("Ensaio clínico", "Clinical Trial[pt]"),
    "meta": ("Metanálise", "Meta-Analysis[pt]"),
    "systematic": ("Revisão sistemática", "systematic[sb]"),
    "review": ("Revisão", "Review[pt]"),
    "observational": ("Estudo observacional", "Observational Study[pt]"),
    "cohort": ("Coorte", "Cohort Studies[mh]"),
    "case_control": ("Caso-controle", "Case-Control Studies[mh]"),
    "cross_sectional": ("Transversal", "Cross-Sectional Studies[mh]"),
    "qualitative": ("Pesquisa qualitativa", "Qualitative Research[mh]"),
    "case_report": ("Relato de caso", "Case Reports[pt]"),
    "guideline": ("Diretriz", "Guideline[pt]"),
    "comparative": ("Estudo comparativo", "Comparative Study[pt]"),
    "validation": ("Estudo de validação", "Validation Study[pt]"),
}
LANGUAGES = {
    "english": "Inglês",
    "portuguese": "Português",
    "spanish": "Espanhol",
    "french": "Francês",
    "german": "Alemão",
    "italian": "Italiano",
    "chinese": "Chinês",
    "japanese": "Japonês",
}
AGES = {
    "child": "child[mh]",
    "adolescent": "adolescent[mh]",
    "adult": "adult[mh]",
    "middle_aged": "middle aged[mh]",
    "aged": "aged[mh]",
    "aged80": "aged, 80 and over[mh]",
    "infant": "infant[mh]",
    "newborn": "infant, newborn[mh]",
}


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    study_types: list[
        Literal[
            "randomized",
            "clinical",
            "meta",
            "systematic",
            "review",
            "observational",
            "cohort",
            "case_control",
            "cross_sectional",
            "qualitative",
            "case_report",
            "guideline",
            "comparative",
            "validation",
        ]
    ] = Field(default_factory=list, max_length=14)
    languages: list[Literal["english", "portuguese", "spanish", "french", "german", "italian", "chinese", "japanese"]] = Field(
        default_factory=list, max_length=8
    )
    date_from: date | None = None
    date_to: date | None = None
    species: Literal["all", "humans", "animals"] = "all"
    sex: Literal["all", "female", "male"] = "all"
    ages: list[Literal["child", "adolescent", "adult", "middle_aged", "aged", "aged80", "infant", "newborn"]] = Field(
        default_factory=list, max_length=8
    )
    availability: Literal["all", "abstract", "full", "free"] = "all"
    medline: bool = False
    exclude_preprints: bool = False
    advanced: str = Field(default="", max_length=2000)
    sort: Literal["pub date", "relevance"] = "pub date"

    @model_validator(mode="after")
    def validate_options(self):
        if (
            any(x not in PUBLICATION_TYPES for x in self.study_types)
            or any(x not in LANGUAGES for x in self.languages)
            or any(x not in AGES for x in self.ages)
        ):
            raise ValueError("Filtro PubMed desconhecido")
        if (
            self.species not in ("all", "humans", "animals")
            or self.sex not in ("all", "female", "male")
            or self.availability not in ("all", "abstract", "full", "free")
            or self.sort not in ("pub date", "relevance")
        ):
            raise ValueError("Filtro PubMed desconhecido")
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("A data inicial deve anteceder a final")
        return self


def build_query(query, filters):
    f = filters if isinstance(filters, Filters) else Filters.model_validate(filters)
    clauses = []
    for values in ([PUBLICATION_TYPES[x][1] for x in f.study_types], [x + "[la]" for x in f.languages], [AGES[x] for x in f.ages]):
        if values:
            clauses.append("(" + " OR ".join(values) + ")")
    if f.date_from or f.date_to:
        fmt = lambda d: d.strftime("%Y/%m/%d")
        clauses.append(
            f'("{fmt(f.date_from) if f.date_from else "1000/01/01"}"[dp] : "{fmt(f.date_to) if f.date_to else "3000/12/31"}"[dp])'
        )
    if f.species != "all":
        clauses.append(f.species + "[mh]")
    if f.sex != "all":
        clauses.append(f.sex + "[mh]")
    if f.availability != "all":
        clauses.append({"abstract": "hasabstract", "full": "full text[sb]", "free": "free full text[sb]"}[f.availability])
    if f.medline:
        clauses.append("medline[sb]")
    if f.exclude_preprints:
        clauses.append("NOT preprint[pt]")
    if f.advanced.strip():
        clauses.append("(" + f.advanced.strip() + ")")
    result = "(" + query.strip() + ")" if clauses else query.strip()
    for clause in clauses:
        result += " " + clause if clause.startswith("NOT ") else " AND " + clause
    if len(result) > 10000:
        raise ValueError("String excessivamente longa")
    return result


def extract_document(data, filename):
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("Limite de 10 MB por ficha")
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext == "txt":
        content = data.decode("utf-8-sig")
    elif ext == "pdf":
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted or len(reader.pages) > 100:
            raise ValueError("Use PDF sem senha com até 100 páginas")
        content = "\n".join(p.extract_text() or "" for p in reader.pages)
    elif ext == "docx":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(x.file_size for x in z.infolist()) > 30 * 1024 * 1024:
                raise ValueError("DOCX descompactado excede 30 MB")
            xml = z.read("word/document.xml")
        tree = ET.fromstring(xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        content = "\n".join("".join(t.text or "" for t in p.findall(".//w:t", ns)) for p in tree.findall(".//w:p", ns))
    else:
        raise ValueError("Use PDF, DOCX ou TXT")
    content = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", content).strip()
    if len(content) < 20:
        raise ValueError("Não foi possível extrair texto suficiente. Use uma ficha textual; OCR não está disponível.")
    return {
        "filename": filename[:200],
        "text": content[:20000],
        "characters": len(content),
        "truncated": len(content) > 20000,
        "sha256": hashlib.sha256(data).hexdigest(),
    }
