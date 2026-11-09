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
    summary = [
        ["FULLMARK • MATRIZ DE EVIDÊNCIAS"],
        ["Pesquisa", snap["review"]["title"]],
        ["Protocolo SHA256", snap["review"]["protocol_hash"]],
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
    searches = [["ID", "String exata", "Tradução PubMed", "Total encontrado", "Limite importação", "Resposta original"]] + [
        [s["id"], s["query"], s["translated_query"], s["total_found"], s["max_records"], json.dumps(s["raw"], ensure_ascii=False)]
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
            f'<styleSheet xmlns="{ns}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF153F35"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="2"><xf fontId="0" fillId="0" borderId="0" xfId="0"><alignment vertical="top" wrapText="1"/></xf><xf fontId="1" fillId="2" borderId="0" xfId="0"><alignment vertical="top" wrapText="1"/></xf></cellXfs></styleSheet>',
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
    labels = [
        f"Registros importados: {p['identified']}",
        f"Duplicatas removidas: {p['duplicates_removed']}",
        f"Triagem concluída: {p['screened']} · pendente: {p['title_abstract_pending']}",
        f"Excluídos no resumo: {p['title_abstract_excluded']}",
        f"Relatórios procurados: {p['reports_sought']}",
        f"Não obtidos: {p['reports_not_retrieved']} · aguardando: {p['reports_retrieval_pending']}",
        f"Textos completos avaliados: {p['reports_assessed']} · disponíveis: {p['reports_available']}",
        f"Excluídos: {p['full_text_excluded']} · avaliação pendente: {p['full_text_pending']}",
        f"Relatórios incluídos: {p['included_reports']}",
    ]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="1050" viewBox="0 0 900 1050"><rect width="900" height="1050" fill="#f5f3eb"/><g font-family="sans-serif"><text x="60" y="60" font-size="24" fill="#153f35">FULLMARK / Fluxo de seleção</text><text x="60" y="90" font-size="15">'
        + ("Concluído" if p["complete"] else "PARCIAL — há etapas pendentes")
        + "</text>"
    )
    for i, label in enumerate(labels):
        y = 120 + i * 90
        if i:
            svg += f'<path d="M450 {y - 25} V{y}" stroke="#153f35" stroke-width="2"/>'
        svg += f'<rect x="50" y="{y}" width="800" height="65" rx="8" fill="#fff" stroke="#153f35"/><text x="75" y="{y + 38}" font-size="17">{escape(label)}</text>'
    svg += '<text x="50" y="970" font-size="13">Contagens de relatórios; estudos distintos não foram agrupados.</text><text x="50" y="995" font-size="13">Modelo operacional inspirado no PRISMA 2020; valide para publicação.</text></g></svg>'
    return svg.encode()
