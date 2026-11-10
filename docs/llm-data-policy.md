# AI 전송 정책 (CORP-008, OPS-010, OPS-003)

## 보내기 전 가리기
`app/agent/redact.py`가 AI(추출기·응답기)에 보낼 문자열에서 식별 정보를 토큰으로 바꾼다.

| 대상 | 토큰 |
|---|---|
| 사업자등록번호(xxx-xx-xxxxx, '사업자(등록)번호' 뒤 10자리) | `[사업자번호]` |
| 법인등록번호(xxxxxx-xxxxxxx) | `[법인번호]` |
| 주민등록번호 | `[주민번호]` |
| 전화·휴대폰(02, 0xx, 010, +82) | `[전화번호]` |
| 이메일 | `[이메일]` |
| 상세주소(도로명+건물번호, 지번, 동·호) | `[주소]` |

폐기물 분류번호(51-03-01), 수치(5%, mg/L, pH), 날짜는 가리지 않는다.
수치 단위가 뒤따르는 "~로 5%" 같은 문장은 주소로 보지 않는다.

## fail-closed
- 가리기 중 오류가 나거나 가린 뒤에도 식별 패턴이 남으면 AI를 부르지 않는다.
- 그 턴은 AI가 꺼진 것처럼 진행한다(버튼 답만 받는 질문 흐름, 응답은 템플릿).
- Trace의 `extraction.llm_blocked`, `responder.llm_blocked`에 이유를 남긴다.

## 사실 근거 문장(quote)
guard는 모델이 실제로 본 '가린 문장'으로 quote를 검사한다. 저장된 사실의 quote도 가린 문장이다.

## 서류 원문
`allow_document_llm`(환경변수 `ALLOW_DOCUMENT_LLM`, 기본 false)이 꺼져 있으면 서류 원문은 AI로 보내지 않는다.
서류 경로는 `extract(..., source="document")`로 불러야 이 차단이 적용된다.

## 보충 설명(assist)에 보내는 자료
사용자가 "왜?", "뭐예요?"라고 물으면 응답 AI에 설명 자료를 더 보낸다(`app/agent/assist.py`): 관련 규칙의 쉬운 설명(`rule_notes.yaml`), 근거 조문 인용, 용어집 설명, 문진 진행 지침(`knowledge/skills/interviewer.md`). 모두 공개 법령과 사람이 쓴 문구라 식별 정보는 없다. 사용자 질문 문장은 다른 payload와 같이 가린 뒤 보낸다. AI가 쓴 설명은 guard가 검사한다(자료에 없는 번호·숫자 금지, `why`는 근거 id 인용 필수). 실패하면 템플릿 문장으로 바꾼다.

## 웹 검색(보충 설명의 마지막 수단)
질문 안내·용어집·규칙 설명에 답할 자료가 없을 때만 웹 검색을 한다(`app/agent/web_search.py`, 기본 꺼짐: `WEB_SEARCH_PROVIDER=none`). 켜면 네이버 검색 API로 사용자 질문 문장을 보낸다. 보내기 전에 식별 정보를 가리고, 가린 뒤에도 남으면 검색하지 않는다. 결과는 허용 도메인(법령·공공기관 사이트)만 쓰고 "공식 자료로 확인" 안내와 출처 주소를 붙인다. 판정에는 쓰지 않는다. 자료가 없어 웹 검색으로 넘어간 질문은 Trace(`responder.assist_matched=false`)에 남아 질문 안내 보강 대상이 된다.

## Trace 기록
`LLMCall.user`에는 가린 프롬프트만 들어가고, 원문의 `user_sha256`·`user_len`, 응답의 `raw_sha256`·`raw_len`이 붙는다.
`trace_store_prompts=false`(`TRACE_STORE_PROMPTS`)면 프롬프트·응답 본문을 비우고 해시와 길이만 남긴다.
