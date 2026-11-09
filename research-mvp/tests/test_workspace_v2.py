import io, json, zipfile
import pytest
from app import db, research, exports, delivery
from app.service import snapshot


def test_filters_query_and_dates():
    f=research.Filters(study_types=['randomized','cohort'],languages=['english','portuguese'],species='humans',date_from='2020-01-01',date_to='2026-11-09',exclude_preprints=True)
    q=research.build_query('exercise OR balance',f)
    assert q.startswith('(exercise OR balance) AND (Randomized Controlled Trial[pt] OR Cohort Studies[mh])')
    assert '(english[la] OR portuguese[la])' in q and 'humans[mh]' in q and q.endswith('NOT preprint[pt]')
    with pytest.raises(ValueError):research.Filters(study_types=['fake'])
    with pytest.raises(ValueError):research.Filters(date_from='2026-01-01',date_to='2020-01-01')


def test_document_upload_and_auth(client,auth):
    assert client.post('/documents/extract',headers={'X-Filename':'a.txt'},content=b'a'*30).status_code==401
    r=client.post('/documents/extract',headers={**auth,'X-Filename':'ficha.txt'},content='Tema: prevenção de quedas em idosos.'.encode())
    assert r.status_code==200 and 'idosos' in r.json()['text'] and len(r.json()['sha256'])==64
    assert client.post('/documents/extract',headers={**auth,'X-Filename':'ficha.exe'},content=b'x'*30).status_code==422
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Produção científica sobre prevenção de quedas.</w:t></w:r></w:p></w:document>')
    assert 'Produção' in research.extract_document(out.getvalue(),'ficha.docx')['text']


def test_draft_edit_then_freeze(client,auth):
    body={'title':'Pesquisa de teste','protocol':{'question':'Quedas podem ser prevenidas?','inclusion':['Idosos'],'exclusion':['Crianças']}}
    rid=client.post('/reviews',headers=auth,json=body).json()['id'];body['title']='Protocolo revisado'
    assert client.put(f'/reviews/{rid}/draft',headers=auth,json=body).status_code==200
    client.post(f'/reviews/{rid}/approve',headers=auth)
    assert client.put(f'/reviews/{rid}/draft',headers=auth,json=body).status_code==409


def test_search_filter_idempotency(client,auth,review):
    h={**auth,'Idempotency-Key':'filter-test-01'};body={'query':'exercise','filters':{'languages':['english']}}
    a=client.post(f'/reviews/{review}/searches',headers=h,json=body);assert a.status_code==202
    assert client.post(f'/reviews/{review}/searches',headers=h,json=body).json()['search_id']==a.json()['search_id']
    body['filters']['languages']=['portuguese']
    assert client.post(f'/reviews/{review}/searches',headers=h,json=body).status_code==409


def test_recommendation_acceptance_is_human_and_no_fulltext_auto(client,auth,review,article):
    with db.Session() as s:
        a=s.get(db.Article,article);a.recommendation={'recommendation':'include','reason':'Matches protocol','quote':'Randomized trial'};s.commit()
    assert client.post(f'/reviews/{review}/recommendations/accept',headers=auth,json={'article_ids':[article],'reason':'Li e aprovei esta inclusão.'}).status_code==200
    detail=client.get('/reviews/'+review,headers=auth).json();assert detail['decisions'][0]['stage']=='title_abstract'
    assert detail['prisma']['included_reports']==0 and any(j['kind']=='pdf' for j in detail['jobs'])


def test_delivery_claim_ack_and_ambiguous_writes(review):
    with db.Session() as s:
        j=delivery.request_delivery(s,s.get(db.Review,review),'drive','test-drive-key');jid=j.id;s.commit()
        out=delivery.claim(s);s.commit();assert out[0]['action']=='folder'
        assert delivery.claim(s)==[]
        delivery.acknowledge(s,jid,{'action':'folder','remote_id':'folder123'});s.commit()
        item=delivery.claim(s)[0];s.commit();assert item['action']=='file' and item['cursor']==0
        delivery.acknowledge(s,jid,{'action':'file','remote_id':'file123','cursor':0});s.commit()
        delivery.claim(s);s.commit();j=s.get(db.Job,jid);j.lease_until=0;s.commit()
        assert delivery.claim(s)==[];s.commit();assert s.get(db.Job,jid).status=='needs_reconciliation'
        snap=snapshot(s,s.get(db.Review,review));assert 'snapshot' not in snap['jobs'][0]['payload']


def test_history_and_methodology_exports(client,auth,review,article):
    r=client.get(f'/reviews/{review}/export/csv',headers=auth);assert r.status_code==200 and 'not browser session CSV' in r.text
    assert client.get(f'/reviews/{review}/export/md',headers=auth).status_code==200
    z=client.get(f'/reviews/{review}/export/zip',headers=auth);assert z.status_code==200
    with zipfile.ZipFile(io.BytesIO(z.content)) as archive:
        assert 'matriz.xlsx' in archive.namelist() and 'historico-pubmed.csv' in archive.namelist()
        assert json.loads(archive.read('artigos-pendentes.json'))==[]
