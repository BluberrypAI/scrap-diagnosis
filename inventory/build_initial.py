import csv, pathlib, hashlib, re, datetime
p=pathlib.Path('.'); out=p/'inventory'; out.mkdir(exist_ok=True)
def read(path):
 with open(path,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(name, fields, rows):
 with open(out/name,'w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
fields='doc_id parent_doc_id title issuer doc_type authority unit version amended_on effective_on version_status_guess url local_path sha256 tags_guess checked_on note'.split()
rows=[]; used=set()
def add(**kw):
 kw.setdefault('checked_on','2026-11-04');kw.setdefault('tags_guess','MAYBE');kw.setdefault('version_status_guess','UNKNOWN'); kw.setdefault('unit','DOC');
 path=kw.get('local_path','')
 if path and (p/path).is_file():kw['sha256']=hashlib.sha256((p/path).read_bytes()).hexdigest();used.add(path)
 rows.append(kw)
def pathnote(s):
 m=re.search(r'sources/raw/[^\s.]+(?:\.[^\s.]+)+',s);return m.group(0).rstrip('.') if m else ''
for x in read('data/interpretation_sources.csv'):
 sid=x['source_id']; path=pathnote(x['note'])
 if sid in ('GUIDE23-QA','ALLBARO','WASTE-A4','WASTE-D1','NIER-PH','NIER-OIL'):continue
 if sid=='ALLBARO-CODE': typ,auth,prefix='DATA','OFFICIAL_GUIDE','DATA-'
 elif sid=='GUIDE23':typ,auth,prefix='GUIDE','OFFICIAL_GUIDE','GUIDE-'
 elif sid=='WONJU26':typ,auth,prefix='QA','QA','QA-'
 else:
  typ,auth='LAW','BINDING';prefix='RULE-' if sid.endswith('RULE') else ('DEC-' if sid.endswith('DEC') else 'ACT-')
 add(doc_id=prefix+sid,title=x['title'],issuer=x['publisher'],doc_type=typ,authority=auth,version=x['law_version_assumed'],amended_on=x['published_on'] if typ=='LAW' else '',effective_on=x['effective_on'],version_status_guess=x['version_check'] if x['version_check'] in ('CURRENT','PENDING','SUPERSEDED') else 'UNKNOWN',url=x['url'],local_path=path,note='기존 자료 메타데이터 재사용: '+x['note'])
for x in read('data/law_sources.csv'):
 if not x['item'].startswith('별표') or not re.fullmatch(r'별표 \d+(의\d+)?',x['item']):continue
 if any(r.get('url')==x['url'] for r in rows):continue
 add(doc_id=x['source_id'],parent_doc_id='DEC-WASTE-DEC' if x['source_id'].startswith('DEC-') else 'RULE-WASTE-RULE',title=x['law_name']+' '+x['item']+' '+x['title'],issuer='법제처 국가법령정보센터',doc_type='LAW',authority='BINDING',unit='ANNEX',amended_on=x['amended_on'],effective_on=x['effective_on'],version_status_guess='CURRENT',url=x['url'],local_path=pathnote(x['note']),note='기존 자료 메타데이터. '+x['note'])
add(doc_id='NOTICE-NIER-2025-21',title='폐기물공정시험기준',issuer='국립환경과학원',doc_type='NOTICE',authority='BINDING',version='제2025-21호',amended_on='2025-08-06',effective_on='2025-08-06',version_status_guess='CURRENT',url='https://www.l.law.go.kr/admRulLsInfoP.do?admRulSeq=2100000263068'.replace('www.l.law','www.law'),local_path='sources/raw/nier-test-2025.zip',tags_guess='G_TEST',note='고시 첨부 ZIP; 본문 주소는 국가법령정보센터')
for x in read('audit/version_search.csv'):
 path=pathnote(x['note'])
 if not x['newer_url'] or not path or not (p/path).exists() or path in used:continue
 typ='REF' if '예고' in x['newer_version'] else 'LAW';prefix='REF-' if typ=='REF' else 'ACT-'
 dates=re.findall(r'20\d{2}-\d{2}-\d{2}',x['newer_version']); eff=dates[0] if dates and typ=='LAW' else ''
 add(doc_id=prefix+'FUTURE-'+str(len(rows)+1),title=x['material'],issuer='법제처 또는 기후에너지환경부',doc_type=typ,authority='REFERENCE' if typ=='REF' else 'BINDING',version=x['newer_version'],effective_on=eff,version_status_guess='PENDING' if typ=='LAW' else 'UNKNOWN',url=x['newer_url'],local_path=path,note=x['note'])
hist=[]
for x in read('audit/annex4_history.csv'):
 path=x['path']; did='RULE-A4-'+x['effective_on']+'-'+x['flSeq']
 hist.append(dict(doc_id=did,title=x['history_item'],amended_on=x['annex_amended_on'],effective_on=x['effective_on'],version_status_guess='SUPERSEDED',url=x['source_url'],downloaded='Y' if path and (p/path).exists() else 'N',reason_if_downloaded='기존 보유 원본; 2023 해설서 기준판 또는 이전 감사 자료'))
 if path and (p/path).exists() and path not in used:add(doc_id=did,parent_doc_id='RULE-WASTE-RULE',title='폐기물관리법 시행규칙 별표 4',issuer='법제처 국가법령정보센터',doc_type='LAW',authority='BINDING',unit='ANNEX',amended_on=x['annex_amended_on'],effective_on=x['effective_on'],version_status_guess='SUPERSEDED',url=x['source_url'],local_path=path,note='기존 보유 별표 연혁. '+x['history_item'])
for name,title,issuer,url in [('tc-moe-qa-casebook-2025-07.pdf','질의회신 사례집 2025년 7월판','환경부',''),('wonju-environment-qa-posted-2026-08-11.pdf','환경분야 질의회신 사례집','환경부','https://www.mcee.go.kr/wonju/web/board/read.do?boardId=1883270&boardMasterId=232&menuId=1025'),('wonju-environment-qa-volume2-posted-2026-08-11.hwp','지정 의료 건설 질의회신 사례집 제2권','환경부','https://www.mcee.go.kr/home/web/policy_data/read.do?menuId=10263&seq=4226'),('wonju-recycling-qa-posted-2026-08-11.pdf','재활용 질의회신 사례집','환경부','https://www.mcee.go.kr/wonju/web/board/read.do?boardId=1883270&boardMasterId=232&menuId=1025')]:
 add(doc_id='QA-'+name.split('.')[0],title=title,issuer=issuer,doc_type='QA',authority='REFERENCE',url=url,local_path='sources/raw/'+name,tags_guess='I_CASES|MAYBE',note='기존 보유본. 법적 효력 및 발행일 추가 확인 필요.')
for file in sorted((p/'sources/raw').glob('*')):
 path=file.as_posix()
 if file.is_file() and path not in used:add(doc_id='REF-UNIDENTIFIED-'+file.stem,title='기존 원본 식별 필요: '+file.name,issuer='',doc_type='REF',authority='REFERENCE',local_path=path,note='기존 파일. 출처·문서명·판 확인 전 분류 금지.')
for x in rows:
 if x['doc_type']=='LAW' and x.get('unit')=='DOC':hist.append(dict(doc_id=x['doc_id'],title=x['title'],amended_on=x.get('amended_on',''),effective_on=x.get('effective_on',''),version_status_guess=x['version_status_guess'],url=x.get('url',''),downloaded='Y' if x.get('local_path') else 'N',reason_if_downloaded='기존 보유 원본' if x.get('local_path') else ''))
logs=[dict(site=x['site'],query=x['query'],searched_on=x['searched_on'],hits=x['result'],collected='',note='이전 감사 검색 이관; '+x['note']) for x in read('audit/version_search.csv')]
for q in ['site:law.go.kr 폐기물관리법 제3조 적용 제외 법률','site:law.go.kr 건설폐기물 재활용촉진 법률 시행령 시행규칙','site:data.go.kr 폐기물 처리업 허가 데이터 폐기물 종류','site:mcee.go.kr 폐기물 의료 건설 질의회신 사례집']:
 logs.append(dict(site='웹 검색(공식 사이트 한정)',query=q,searched_on='2026-11-04',hits='검색결과 확인',collected='일부 목록화',note='검색 결과의 범위는 전수 아님'))
write('inventory.csv',fields,rows);write('version_history.csv','doc_id title amended_on effective_on version_status_guess url downloaded reason_if_downloaded'.split(),hist);write('search_log.csv','site query searched_on hits collected note'.split(),logs)
write('unreachable.csv','url found_on_page title attempted_at failure_type error_detail retries partial_result manual_steps note'.split(),[])
print('inventory',len(rows),'history',len(hist),'searches',len(logs),'files',len(used))
