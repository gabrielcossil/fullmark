"""Portable OOXML export: inline string cells never execute untrusted formulas."""

import io, json, zipfile, math
from datetime import datetime, timezone
from html import escape


def xlsx(snap):
    p = snap["prisma"]
    decisions = {}
    stamp = lambda ts: datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")
    for d in sorted(snap["decisions"], key=lambda x: (x["created_at"], x["id"])):
        decisions[(d["article_id"], d["stage"])] = d
    protocol = snap["review"]["protocol"]
    summary = [
        ["FULLMARK • MATRIZ DE EVIDÊNCIAS"],
        ["Pesquisa", snap["review"]["title"]],
        ["Protocolo SHA256", snap["review"]["protocol_hash"]],
        ["Pergunta", protocol.get("question", "")],
        ["Critérios de inclusão", "\n".join(protocol.get("inclusion", []))],
        ["Critérios de exclusão", "\n".join(protocol.get("exclusion", []))],
        ["Observações", protocol.get("observations", "")],
        ["Filtros aprovados", json.dumps(protocol.get("filters", {}), ensure_ascii=False)],
        ["Exportado UTC", stamp(snap["exported_at"])],
        ["PRISMA completo", "Sim" if p["complete"] else "Não · há pendências"],
        ["Métrica", "Quantidade"],
    ] + [[k, v] for k, v in p.items() if isinstance(v, int) and not isinstance(v, bool)]
    matrix = [
        [
            "ID",
            "Título",
            "Autores",
            "Ano",
            "DOI",
            "PMID",
            "Fonte",
            "Resumo",
            "Sugestão IA",
            "Título/resumo humano",
            "Texto completo humano",
            "Motivo texto completo",
            "Motivo título/resumo",
            "Estratégias de origem",
            "Filtros",
            "Justificativa IA",
            "PDF/licença",
            "Extração com páginas",
        ]
    ]
    for a in snap["articles"]:
        m = a["metadata_json"]
        ta = decisions.get((a["id"], "title_abstract"), {})
        ft = decisions.get((a["id"], "full_text"), {})
        matrix.append(
            [
                a["id"],
                m.get("title"),
                "; ".join(m.get("authors", [])),
                m.get("year"),
                m.get("doi"),
                m.get("pmid"),
                m.get("url"),
                m.get("abstract"),
                json.dumps(a["recommendation"], ensure_ascii=False),
                ta.get("verdict", "pending"),
                ft.get("verdict", "pending"),
                ft.get("reason"),
                ta.get("reason"),
                "\n".join(
                    s["query"]
                    for s in snap["searches"]
                    if s["id"] in {x["search_id"] for x in snap["records"] if x["article_id"] == a["id"]}
                ),
                json.dumps(
                    [
                        {"search_id": s["id"], "filters": s["raw"].get("fullmark", s["raw"]).get("filters", {})}
                        for s in snap["searches"]
                        if s["id"] in {x["search_id"] for x in snap["records"] if x["article_id"] == a["id"]}
                    ],
                    ensure_ascii=False,
                ),
                a["recommendation"].get("reason", ""),
                json.dumps(a["pdf"], ensure_ascii=False),
                json.dumps(a["extraction"], ensure_ascii=False),
            ]
        )
    extracted = [["ID artigo", "Campo", "Valor", "Página", "Citação literal", "Revisor", "Fonte PDF"]]
    for a in snap["articles"]:
        for item in a["extraction"].get("items", []):
            extracted.append(
                [
                    a["id"],
                    item["field"],
                    item["value"],
                    item["page"],
                    item["quote"],
                    a["extraction"].get("reviewed_by"),
                    a["pdf"].get("source_url"),
                ]
            )
    audits = [["Quando UTC", "Ator", "Ação", "Payload"]] + [
        [stamp(x["created_at"]), x["actor"], x["action"], json.dumps(x["payload"], ensure_ascii=False)] for x in snap["audit"]
    ]
    searches = [
        [
            "ID",
            "String exata",
            "Tradução PubMed",
            "Total encontrado",
            "Limite importação",
            "Filtros",
            "Importados",
            "Duplicatas",
            "Novos únicos",
            "Resposta original",
        ]
    ] + [
        [
            s["id"],
            s["query"],
            s["translated_query"],
            s["total_found"],
            s["max_records"],
            json.dumps(s["raw"].get("fullmark", s["raw"]).get("filters", {}), ensure_ascii=False),
            s["raw"].get("stats", {}).get("imported", 0),
            s["raw"].get("stats", {}).get("duplicates", 0),
            s["raw"].get("stats", {}).get("new", 0),
            json.dumps(s["raw"], ensure_ascii=False),
        ]
        for s in snap["searches"]
    ]
    sheets = {"Resumo PRISMA": summary, "Matriz": matrix, "Extração": extracted, "Auditoria": audits, "Buscas": searches}
    buf = io.BytesIO()
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

    def col(n):
        s = ""
        while n:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s

    def safe(v):
        import re

        return escape(re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", str(v if v is not None else ""))[:32767])

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        types = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        for i in range(1, len(sheets) + 1):
            types += f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        z.writestr("[Content_Types].xml", types + "</Types>")
        z.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        z.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            + "".join(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>' for i, name in enumerate(sheets, 1))
            + "</sheets></workbook>",
        )
        rel = (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                for i in range(1, len(sheets) + 1)
            )
            + '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
        )
        z.writestr("xl/_rels/workbook.xml.rels", rel)
        z.writestr(
            "xl/styles.xml",
            f'<styleSheet xmlns="{ns}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF123B66"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="2"><xf fontId="0" fillId="0" borderId="0" xfId="0"><alignment vertical="top" wrapText="1"/></xf><xf fontId="1" fillId="2" borderId="0" xfId="0"><alignment vertical="top" wrapText="1"/></xf></cellXfs></styleSheet>',
        )
        for i, (name, rows) in enumerate(sheets.items(), 1):
            xml = f'<worksheet xmlns="{ns}"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols><col min="1" max="1" width="24" customWidth="1"/><col min="2" max="{max(map(len, rows))}" width="45" customWidth="1"/></cols><sheetData>'
            for ri, row in enumerate(rows, 1):
                line_count = max(
                    sum(max(1, math.ceil(len(part) / (24 if ci == 0 else 45))) for part in str(v or "").split("\n"))
                    for ci, v in enumerate(row)
                )
                height = 34 if ri == 1 else min(210, max(26, 15 * line_count + 8))
                xml += f'<row r="{ri}" ht="{height}" customHeight="1">'
                for ci, v in enumerate(row, 1):
                    ref = f"{col(ci)}{ri}"
                    style = 1 if ri == 1 else 0
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        xml += f'<c r="{ref}" s="{style}"><v>{v}</v></c>'
                    else:
                        xml += f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{safe(v)}</t></is></c>'
                xml += "</row>"
            xml += "</sheetData>"
            if name == "Resumo PRISMA":
                xml += '<mergeCells count="1"><mergeCell ref="A1:B1"/></mergeCells>'
            if name != "Resumo PRISMA":
                xml += f'<autoFilter ref="A1:{col(len(rows[0]))}{len(rows)}"/>'
            z.writestr(f"xl/worksheets/sheet{i}.xml", xml + "</worksheet>")
    return buf.getvalue()


def prisma_svg(p):
    # PRISMA 2020 database-only layout: side exclusions and vertical selection stages.
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1150" height="1130" viewBox="0 0 1150 1130"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8Z" fill="#345471"/></marker></defs><rect width="1150" height="1130" fill="white"/><g font-family="Arial,sans-serif" fill="#152e49"><text x="40" y="40" font-size="24" font-weight="bold">FULLMARK · Fluxo PRISMA 2020</text><text x="40" y="68" font-size="14">'
        + ("Seleção concluída" if p["complete"] else "PARCIAL · há buscas ou decisões pendentes")
        + "</text>"
    ]

    def box(x, y, w, h, lines, fill="#f1f6fb"):
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="#6484a2"/>')
        for i, line in enumerate(lines):
            parts.append(f'<text x="{x + 16}" y="{y + 27 + i * 23}" font-size="15">{escape(str(line))}</text>')

    def arrow(x, y, xx, yy):
        parts.append(f'<path d="M{x} {y} L{xx} {yy}" stroke="#345471" stroke-width="1.6" fill="none" marker-end="url(#arrow)"/>')

    for y, h, label in [(110, 150, "Identificação"), (300, 570, "Seleção"), (910, 115, "Inclusão")]:
        box(32, y, 45, h, [], "#dfeefa")
        parts.append(f'<text transform="translate(61,{y + h - 20}) rotate(-90)" font-size="15" font-weight="bold">{label}</text>')
    box(
        110,
        110,
        470,
        115,
        ["Registros identificados em bases de dados", f"PubMed (n = {p['identified']})", "Contagem dos registros efetivamente importados"],
    )
    box(
        670,
        110,
        440,
        115,
        ["Registros removidos antes da triagem", f"Duplicatas removidas (n = {p['duplicates_removed']})", "Remoções por automação: 0"],
    )
    arrow(580, 165, 670, 165)
    arrow(345, 225, 345, 300)
    box(
        110,
        300,
        470,
        95,
        [
            f"Registros para triagem (n = {p['identified'] - p['duplicates_removed']})",
            f"Triagem concluída: {p['screened']} · pendente: {p['title_abstract_pending']}",
        ],
    )
    box(670, 300, 440, 95, ["Registros excluídos após título/resumo", f"(n = {p['title_abstract_excluded']})"])
    arrow(580, 345, 670, 345)
    arrow(345, 395, 345, 455)
    box(110, 455, 470, 95, ["Relatórios procurados para recuperação", f"(n = {p['reports_sought']})"])
    box(
        670,
        455,
        440,
        95,
        [f"Relatórios não recuperados (n = {p['reports_not_retrieved']})", f"Recuperação pendente (n = {p['reports_retrieval_pending']})"],
    )
    arrow(580, 500, 670, 500)
    arrow(345, 550, 345, 615)
    box(
        110,
        615,
        470,
        115,
        [
            "Relatórios avaliados para elegibilidade",
            f"(n = {p['reports_assessed']})",
            f"Avaliação de texto pendente: {p['full_text_pending']}",
        ],
    )
    reasons = [f"Relatórios excluídos (n = {p['full_text_excluded']})"]
    for reason, n in list(p["full_text_exclusion_reasons"].items())[:4]:
        reasons.append(reason[:45] + f" (n = {n})")
    if len(p["full_text_exclusion_reasons"]) > 4:
        reasons.append("Demais motivos no histórico JSON")
    box(670, 615, 440, 165, reasons)
    arrow(580, 670, 670, 670)
    arrow(345, 730, 345, 910)
    box(
        110,
        910,
        470,
        105,
        [f"Relatórios incluídos (n = {p['included_reports']})", "Estudos incluídos: agrupamento humano pendente"],
        "#dfeefa",
    )
    parts.append(
        '<text x="32" y="1060" font-size="12">Adaptado de PRISMA 2020 · Page et al., BMJ 2021;372:n71 · CC BY 4.0</text><text x="32" y="1082" font-size="12">https://www.prisma-statement.org/prisma-2020-flow-diagram · Motivos completos no histórico.</text><text x="32" y="1104" font-size="12">Resultados totais do PubMed podem exceder o limite importado. Não confundir relatórios com estudos distintos.</text></g></svg>'
    )
    return "".join(parts).encode()


def history_csv(snap):
    import csv

    out = io.StringIO(newline="")
    w = csv.writer(out)
    w.writerow(
        [
            "Source",
            "Search number",
            "Query",
            "Search Details / querytranslation",
            "Results",
            "Imported",
            "Duplicates",
            "New unique",
            "Filters",
            "Executed UTC",
            "Sort",
            "Warnings",
        ]
    )
    safe = lambda value: "'" + str(value) if str(value).lstrip().startswith(("=", "+", "-", "@")) else str(value)
    for i, s in enumerate(sorted(snap["searches"], key=lambda x: (x["created_at"], x["id"])), 1):
        raw = s["raw"]
        context = raw.get("fullmark", raw)
        stats = raw.get("stats", {})
        w.writerow(
            [
                safe(x)
                for x in [
                    "NCBI E-utilities (not browser session CSV)",
                    i,
                    s["query"],
                    s["translated_query"],
                    s["total_found"],
                    stats.get("imported", 0),
                    stats.get("duplicates", 0),
                    stats.get("new", 0),
                    json.dumps(context.get("filters", {}), ensure_ascii=False),
                    datetime.fromtimestamp(raw.get("executed_at", s["created_at"]), timezone.utc).isoformat(),
                    context.get("filters", {}).get("sort", "pub date"),
                    json.dumps(raw.get("esearchresult", {}).get("warninglist", {}), ensure_ascii=False),
                ]
            ]
        )
    return ("\ufeff" + out.getvalue()).encode("utf-8")


def methodology(snap):
    r = snap["review"]
    p = r["protocol"]
    return "\n".join(
        [
            "# Pacote de metodologia · " + r["title"],
            "",
            "## Instrução para o redator / Claude",
            "Redija uma proposta de metodologia exclusivamente a partir dos dados auditáveis abaixo. Não invente bases, datas, contagens, critérios, resultados ou avaliação de qualidade. Identifique pendências. Preserve as strings exatamente. A aprovação científica cabe ao responsável. Não redija resultados que não constem dos arquivos.",
            "",
            "## Protocolo",
            json.dumps(p, ensure_ascii=False, indent=2),
            "",
            "## Estratégias efetivamente executadas",
            json.dumps(
                [
                    {"query": s["query"], "translated": s["translated_query"], "total_found": s["total_found"], "raw": s["raw"]}
                    for s in snap["searches"]
                ],
                ensure_ascii=False,
                indent=2,
            ),
            "",
            "## Contagens e pendências",
            json.dumps(snap["prisma"], ensure_ascii=False, indent=2),
            "",
            "Este prompt é uma base provisória. O modelo editorial da Fullmark será incorporado quando fornecido.",
        ]
    )


def package(snap):
    from . import files

    out = io.BytesIO()
    missing = []
    size = 0
    latest = {}
    for d in sorted(snap["decisions"], key=lambda x: (x["created_at"], x["id"])):
        latest[(d["article_id"], d["stage"])] = d["verdict"]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("matriz.xlsx", xlsx(snap))
        z.writestr("prisma.svg", prisma_svg(snap["prisma"]))
        z.writestr("historico-pubmed.csv", history_csv(snap))
        z.writestr("historico-completo.json", json.dumps(snap, ensure_ascii=False, indent=2))
        z.writestr("metodologia.md", methodology(snap))
        for a in snap["articles"]:
            if latest.get((a["id"], "title_abstract")) != "include":
                continue
            if a["pdf"].get("status") != "available":
                missing.append(
                    {
                        "title": a["metadata_json"].get("title"),
                        "doi": a["metadata_json"].get("doi"),
                        "url": a["metadata_json"].get("url"),
                        "reason": a["pdf"].get("reason", "PDF legal não disponível"),
                    }
                )
                continue
            content = files.get(a["pdf"]["path"])
            if size + len(content) > 50 * 1024 * 1024:
                missing.append(
                    {"title": a["metadata_json"].get("title"), "reason": "Limite de 50 MB do ZIP; baixe este PDF individualmente"}
                )
                continue
            z.writestr("artigos/" + a["metadata_json"].get("pmid", a["id"]) + ".pdf", content)
            size += len(content)
        z.writestr("artigos-pendentes.json", json.dumps(missing, ensure_ascii=False, indent=2))
    return out.getvalue()
