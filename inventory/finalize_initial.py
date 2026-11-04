import csv, pathlib, datetime, collections, hashlib
p=pathlib.Path('inventory'); now=datetime.datetime.now().astimezone().isoformat(timespec='seconds')
def read(n):
 with open(p/n,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(n,fields,rows):
 with open(p/n,'w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
rows=read('inventory.csv'); fields=list(rows[0]);
for r in rows:
 if r['local_path']=='sources/raw/law-284397.pdf':r.update(doc_id='ACT-WASTE-ACT',title='폐기물관리법',issuer='법제처 국가법령정보센터',doc_type='LAW',authority='BINDING',version='법률 제21467호',amended_on='2026-03-17',effective_on='2026-09-18',version_status_guess='CURRENT',url='https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=284397',note='기존 감사의 기준일 시행본 확인.')
 if r['local_path']=='sources/raw/wonju-recycling-qa-posted-2026-08-11.pdf':r['note']+=' 환경부 2018 게시 사례집 PDF와 동일본 여부는 해시 대조 전 미확인.'
rows.append(dict.fromkeys(fields,''));rows[-1].update(doc_id='DATA-HWASEONG-2026',title='화성시 사업장폐기물 처리업체 현황',issuer='경기도 화성시',doc_type='DATA',authority='OFFICIAL_GUIDE',unit='DOC',version='2026-07-15',version_status_guess='UNKNOWN',url='https://www.data.go.kr/data/3046882/fileData.do',tags_guess='H_FACILITY|MAYBE',checked_on='2026-11-04',note='포털 미리보기에서 업종·업체명·주소 등 확인. 허가 폐기물 종류·분류번호 열 여부 미확인; 전체 컬럼 검토 필요.')
write('inventory.csv',fields,rows)
logs=read('search_log.csv'); lf=list(logs[0])
for q in ['site:nier.go.kr 39482 2026-449 폐기물공정시험기준','site:allbaro.or.kr 111210 폐기물 코드','site:data.go.kr 폐기물처리업체 현황 폐기물 종류 허가']:
 logs.append(dict(site='웹 검색(공식 사이트 한정)',query=q,searched_on='2026-11-04',hits='검색결과 확인',collected='일부 목록화',note='전수 검색 아님'))
write('search_log.csv',lf,logs)
uf='url found_on_page title attempted_at failure_type error_detail retries partial_result manual_steps note'.split()
fails=[]
def fail(url,found,title,typ,err,partial,manual,note=''):
 fails.append(dict(url=url,found_on_page=found,title=title,attempted_at=now,failure_type=typ,error_detail=err,retries='0',partial_result=partial,manual_steps=manual,note=note))
fail('https://www.allbaro.or.kr/05_wsc/wsc_notice_view.retrieve.do?board_name=06&seq=111210','audit/final_audit_report.md','올바로 공지 111210','OTHER','웹 도구: URL is not accessible','기존 감사에서 제목 확인','올바로 공지에서 111210을 검색해 본문 및 첨부 선택','기존 감사에는 인증서 이름 불일치 기록; 주소의 게시판 종류는 추정')
fail('https://ecolibrary.me.go.kr','audit/final_audit_report.md','환경정보도서관 구 주소','TIMEOUT','웹 도구: Timeout fetching','없음','현 도서관 포털에서 기관 선택 후 폐기물 자료 검색')
fail('https://www.mcee.go.kr/home/web/policy_data/read.do?menuId=10263&seq=4226','docs/interpretation_report.md','지정 의료 건설 질의회신 사례집 게시물','OTHER','웹 도구: URL is not accessible','기존 HWP 보유; 게시물 원본과 해시 일치 미확인','게시물에서 제2권 HWP 첨부를 선택')
fail('https://opinion.lawmaking.go.kr/gcom/admpp/47640?announceType=TYPE6&mappingAdmRulSeq=2000000332554&pageIndex=1','audit/final_audit_report.md','폐기물공정시험기준 행정예고 2026-449','OTHER','웹 도구: URL is not accessible','이전 감사에서 본문 확인; 첨부 ZIP 미확보','국립환경과학원 행정예고에서 2026-449 검색 후 첨부 ZIP 선택','이전 감사의 ZIP 직접 주소는 기록되지 않아 동일 주소 재시도 불가')
write('unreachable.csv',uf,fails)
counts=collections.Counter(r['doc_type'] for r in rows)
(p/'progress.md').write_text('''# 수집 진행 현황\n\n기준일: 2026-11-04 한국시간. 다음 작업자는 이 문서를 먼저 읽고 계속한다.\n\n- 법령·별표·위임 행정규칙: **진행 중**. 기존 보유분과 폐기물관리법 일부만 정리. 5개 법령군 전체, 적용 제외 관련 법률, 전체 별표·별지·위임 규칙 및 개정 이력 미완료.\n- 구판: **진행 중**. 기존 별표 4 보유분과 이전 연혁을 이관; 보유 해설·사례집별 전제 판 미확인.\n- 해설서·안내서: **진행 중**. 2023 분류 설명서 보유. 기관별 전수와 생활법령 미완료.\n- 사례: **진행 중**. 보유 사례집 일부 목록화. 연도별 사례집, 해석례·판례 전수 미완료.\n- 데이터: **진행 중**. 올바로 조회 및 화성시 예시 위치만 등록. 전체 열과 전국 목록 미확인.\n- 접근 실패: 이전 감사의 실패 대상 일부 재시도. `unreachable.csv` 참조; 이전 ZIP 직접 주소 식별 및 재시도 필요.\n\n기존 `audit/version_search.csv`는 당시 검색 기록을 그대로 이관한 것이며 이번 조사 전수 결과가 아니다. 현재판·예정판은 11월 4일 기준 추정이며 개별 판·공포일을 재확인한다. `REF-UNIDENTIFIED`는 문서 식별을 마쳐야 한다. 별지서식과 미확보 원본을 계속 수집하고, 범위별 완료 때 CSV와 본 파일을 갱신한다.\n''',encoding='utf-8')
(p/'collect_report.md').write_text('# 수집 보고 (중간)\n\n기준일 2026-11-04 한국시간. **전수 수집 미완료**.\n\n자료 유형별 목록 행: '+', '.join(f'{k} {v}건' for k,v in sorted(counts.items()))+' (행 수이며 중복 원본·미식별 자료 포함).\n\n검색 기록 '+str(len(logs))+'건(이전 감사 이관 포함), 확인된 접근 실패 '+str(len(fails))+'건. 실패 유형: '+', '.join(f'{k} {v}건' for k,v in collections.Counter(x['failure_type'] for x in fails).items())+'. 사람이 확인할 대상과 경로는 unreachable.csv 참조.\n\n법령군별 본문·별표·서식·위임 고시 전수, 개정 연혁, 제외 법률, 기관별 안내서, 생활법령, 연도별 사례집, 모든 법령해석례·판례, 데이터 열·공개 사업자 목록이 남아 있다. 원본 보유 사례집의 법적 효력은 보수적으로 REFERENCE로 두고 머리말 추가 확인이 필요하다. 신규 다운로드는 없다.\n',encoding='utf-8')
print('rows',len(rows),'counts',counts,'failures',len(fails),'searches',len(logs))
