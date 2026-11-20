# DFSA v0.1 pipeline E2E

실제 Orchestrator와 Module A/B/C를 연결하는 기능 검증이다. 정량 Evaluation,
Benchmark, Precision/Recall/F1 또는 품질 평가 runner는 포함하지 않는다.
RiskPath의 기존 `evaluation` 다섯 필드는 Public Contract에 따라 검증한다.

## Git 및 변경 범위

- 작업 브랜치: `test/e2e-pipeline-v0.1`
- 생성 기준, HEAD, 로컬 `origin/main`: `176eb4bd1700b202342f0780ca789d18db992a27`
- GitHub 연결 도구로 조회한 원격 `main`도 같은 SHA이며 PR #10은 merged이다.
  `git ls-remote`는 로컬 프록시 연결 실패로 확인하지 못해 연결 도구로 대체했다.
- 시작 시 working tree와 staging area는 비어 있었다. 추가 파일은 전부 `tests/e2e/`에 있다.
- 기존 Module, Orchestrator, Contract, 공통 fixture/설정/문서는 수정하지 않았다.
- branch 생성, reset/rebase/merge, commit, push, PR 생성은 수행하지 않았다.

## 실제 호출과 외부 경계

`conftest.py`는 다음 실제 함수 객체를 `monkeypatch`로 Orchestrator에 직접 연결한다.
종료 시 기존 연결을 복구한다. A/B/C 함수나 내부 business logic을 stub으로 바꾸지 않는다.

| 단계 | 실제 함수 |
| --- | --- |
| A | `dfsa.modules.search.run_search` (`runner.py`) |
| B | `dfsa.modules.profiling.run_profiling` (`pipeline.py`) |
| C | `dfsa.modules.risk.engine.run_risk` |
| Service | `dfsa.service.orchestrator.run_pipeline` |

호출 관찰은 일시적인 `sys.setprofile` callback으로 수행한다. 실제 함수의 입력과 반환값을
deep copy로 기록하며, 기존 profiler도 종료 시 복구한다. 모듈 응답을 만들어 주입하지 않는다.

Fake 경계는 `provider.urlopen`의 SerpApi JSON, `fetch._build_opener().open`의 HTML HTTP 응답,
`socket.getaddrinfo`의 DNS 답변이다. 실제 Provider의 JSON 검증, 검색어 생성, URL 정규화,
관련성 판단, URL 중복 제거, B의 URL/redirect 정책, HTML parsing, 동일인 검증, Exposure
추출·검증·병합, C의 규칙·상태·설명 생성이 모두 실행된다. 시계와 request ID는 실제 구현을 쓴다.

테스트는 실제 API key 대신 명시적인 가짜 환경변수를 설정한다. 원래 환경변수는 복구하며,
키 누락 시의 명시적 실패도 별도로 검증한다. DNS/HTTP의 미등록 경로는 즉시 실패하고,
socket 연결 및 일반 urllib HTTP 진입점도 차단한다. 모든 HTML과 인물 정보는 합성 데이터다.

## 파일

| 파일 | 역할 |
| --- | --- |
| `conftest.py` | Offline HTTP/DNS, 실제 함수 wiring, 호출 관찰, 요청별 fixture |
| `test_pipeline_offline.py` | E2E-01~15 및 두 가지 추가 회귀 검증, 총 43개 |
| `fixtures/*.html` | profile, mirror, other, uncertain, fragmented, empty 합성 HTML 6개 |
| `live_pipeline.py` | pytest 수집에서 제외되는 수동 Live 실행기 |
| `test_live_preparation.py` | Live opt-in/범위/예산/IP 고정/출력 제한, 통신 오류·정리 및 HTTP 프레이밍을 offline으로 검증, 총 46개 |

## 시나리오별 실행 결과

2026-11-20, Windows, 기존 `.venv`, Python 3.12.2 / pytest 9.2.0에서 실행했다.

| 시나리오 | 검증 | 결과 |
| --- | --- | --- |
| E2E-01 | 실제 전체 Pipeline, HTML Evidence, 8종 Exposure 및 5개 RiskPath | 1 passed |
| E2E-02 | 빈 배열/명시적 0건, B/C 호출 생략, summary/JSON | 2 passed |
| E2E-03 | timeout/network/provider 오류/잘못된 JSON, A 전체 실패 | 4 passed |
| E2E-04 | 첫째 또는 둘째 Query 실패, 사용 가능한 결과와 오류 보존 | 2 passed |
| E2E-05 | confirmed지만 분절 Evidence로 추출 0건, empty/uncertain/rejected | 4 passed |
| E2E-06 | 정상 Source와 fetch/parse/unsupported 실패의 공존, C 실행 | 3 passed |
| E2E-07 | 모든 Source fetch/parse 실패, C 생략 | 1 passed |
| E2E-08 | 다른 인물의 별도 페이지와 같은 페이지의 형제 card 제외 | 1 passed |
| E2E-09 | URL 중복 제거, Exposure 병합, 서로 다른 Source/Evidence 보존 | 1 passed |
| E2E-10 | R01~R05 개별 trigger, R01 advisor/collaborator 구분, trigger 미충족 | 7 passed |
| E2E-11 | Source/Exposure/Request ID와 모든 참조의 무결성 | 1 passed |
| E2E-12 | JSON round-trip, 추가 필드/누락 evaluation/summary/stage 거부 | 4 passed |
| E2E-13 | Subject 불변, 두 인물 및 세 번째 0건 요청 격리 | 1 passed |
| E2E-14 | A/B의 예상 밖 transport RuntimeError 전파 및 후속 단계 미실행 | 2 passed |
| E2E-15 | socket/DNS/HTTP 차단, 미등록 경로, key 누락, private redirect/DNS 차단 | 7 passed |
| 추가 | public redirect의 원래 Source URL 보존, A/B 오류 순서 보존 | 2 passed |
| Live 준비 | 실제 네트워크 없이 opt-in, 제한, IP 고정, 출력 및 오류/0건 구분, 본문 읽기·프레이밍 회귀 | 46 passed |

## 실제 생성 결과와 Contract

정상 합성 profile에서 `identity`, `contact`, `affiliation`, `relationship`, `activity`,
`interest`, `account`, `temporal` Exposure가 각각 하나씩 생성된다. relationship의
`relation`은 `advisor`이다. account 링크는 Evidence로만 처리하며 추가 요청하지 않는다.

| Rule | Category | 현재 구현의 상태 |
| --- | --- | --- |
| R01 | authority_impersonation | advisor + 보조 근거는 supported, collaborator는 candidate |
| R02 | academic_impersonation | candidate |
| R03 | recruitment_impersonation | candidate |
| R04 | event_impersonation | candidate |
| R05 | account_impersonation | candidate |

Source ID는 A 출력부터 B 및 최종 결과까지, Exposure ID는 B 출력부터 C 입력 및
RiskPath 참조까지 유지된다. 모든 실제 요청·응답과 최종 결과의 request ID가 일치한다.
ID는 요청 범위 안에서 해석한다. 서로 다른 요청에서 `src_001`, `exp_001`이 재사용되어도
같은 항목이라는 의미가 아니다. C의 reason/recommendations는 최종 결과에서 그대로 보존된다.

모든 RiskPath는 실제 존재하는 Exposure를 참조하고 evaluation 필수 다섯 값을 보유한다.
정상 결과의 summary는 검색 1 / confirmed Source 1 / Exposure 8 / RiskPath 5이다.
최종 DFSAResult의 필수 필드와 list 직렬화, JSON round-trip 및 잘못된 필드 거부를 검증했다.

## 실행 기록과 기존 실패

```powershell
.venv/Scripts/python.exe -m pytest tests/e2e -v
# 89 passed
.venv/Scripts/python.exe -m pytest tests/modules
# 1064 passed, 1 failed
.venv/Scripts/python.exe -m pytest tests/contract tests/integration
# 148 passed
.venv/Scripts/python.exe -m pytest
# 1301 passed, 1 failed (1302 collected)
git diff --check
# 오류 없음
git status --short
# ?? tests/e2e/
```

본문 읽기 오류 수정 전 E2E 56개를 역순으로 실행한 결과는 56 passed였다. Live 실행기는 실제 호출하지 않았다.
Offline 검증 중 Live 실행기의 진입점은 가짜 transport를 주입한 상태에서만 검사했다.

기존 실패는 `tests/modules/profiling/test_parsing.py:169`의
`test_raw_normalized_and_original_offsets`이다. 변경 전에도 전체 1213개 중
1212 passed / 1 failed였고 추가 후에도 동일한 한 개만 실패한다.

Live 응답 본문 읽기 회귀 검증 19개를 추가했다. 수정 전에는 새 검증 중 6개가 실패했고,
그 수정 후에는 기존 56개를 포함해 당시 75개가 통과했다. `LiveHTTP.request()`가 반환한 뒤의
`Response.read()`에도 연결·헤더 수신과 같은 `OSError` / `HTTPException` 변환을 적용했다.
Timeout은 안전한 `TimeoutError`를 reason으로 가진 `URLError`, reset/IncompleteRead는
고정된 메시지의 `URLError`로 전달한다. 기존 A의 SEARCH_TIMEOUT/SEARCH_NETWORK_ERROR와
B의 timeout/network_error를 그대로 사용하며 새 Public Error Code는 없다.
원시 예외 체인은 출력에서 숨기고, 부분 본문을 빈 응답이나 성공 결과로 반환하지 않는다.
정상 읽기, 세 단계의 통신 실패, A의 정상 Query 결과 보존, B의 부분 HTML 폐기,
응답·연결 정리 및 실패 후 요청 예산 유지도 Fake DNS/HTTPS로 검증했다.
응답 close가 실패하더라도 finally에서 연결을 닫으며, 내부 RuntimeError는 변환하지 않는다.

이후 조기 EOF 문제에 대한 프레이밍 회귀 검증 14개를 추가해 현재 E2E는 총 89 passed이다.
예외를 직접 던지는 Fake 대신 `BytesIO` 기반 가짜 socket과 실제 `HTTPResponse.begin()/read()`로
재현했다. 수정 전 새 검증 3개가 실패했고, 수정 후 정상 길이/짧은 길이, 정상 Chunked/
종료 Chunk 누락/Chunk 데이터 부족, 길이 없는 응답, 1 MiB 정확/초과, 부분 성공 보존,
정리 및 실패 후 요청 예산 검증이 통과했다.

`LiveHTTP.search()`는 64 KiB 이하로 나눠 최대 1 MiB + 초과 감지용 1 byte까지 읽는다.
EOF 전에 JSON을 해석하지 않으며, non-chunked 응답에 Content-Length가 있으면 실제 총수신
길이를 비교해 부족한 경우 안전한 URLError로 실패시킨다. 중복/잘못된 길이도 거부한다.
Chunked 디코딩은 표준 HTTPResponse에 맡긴다. 크기 제한 이내의 응답도 EOF까지 읽으므로
종료 Chunk 누락이나 Chunk 데이터 부족 시 IncompleteRead가 기존 P1 정책으로 변환된다.
Content-Length가 없는 non-chunked 응답은 연결 종료를 본문 끝으로 인정한다. 이 경우
통신 예외 없이 닫힌 연결이 의도적 종료인지 조기 종료인지는 판별할 수 없으며, 유효 JSON에
대해 근거 없는 완전성을 보장하지 않는다. 기존 Public Error Code와 네트워크 보안 정책은 유지한다.

원인은 `tests/modules/profiling/fixtures/html/people.html`의 줄바꿈이다.
`git ls-files --eol`은 `i/lf w/crlf`를 보여 준다. 실제 parser에 작업 트리 바이트와
`git show HEAD:<path>` 바이트를 각각 넣어 확인한 결과는 아래와 같다.

```text
working-tree raw_text: '  Original CASE\r\n  ' -> LF assertion False
HEAD-blob raw_text:    '  Original CASE\n  '   -> LF assertion True
```

기존 테스트는 LF 문자열과 완전히 같아야 한다고 가정한다. 원문을 보존하는 parser가
CRLF를 유지하므로 Windows checkout에서 실패한다. 기존 fixture/설정 변경은 허용 범위 밖이므로
그대로 두었다. 테스트 기대값 완화, skip, xfail로 실패를 숨기지 않았다.

이번 합성 E2E에서는 새 A/B/C 통합 결함을 발견하지 않았다. 다만 중앙 명세 §20에는
supported 세부 정책이 미결로 남아 있고 병합된 Module C는 R01 정책을 구현했다.
테스트는 현재 병합 동작을 기록할 뿐 팀 정책을 새로 정하지 않는다. 또한 AGENTS의
구현 전 설명과 명세의 Evaluation 계획은 현재 코드 및 이번 요청의 합의와 차이가 있다.
해당 공통 문서는 이번 범위에서 변경하지 않았다.

## Live 실행 준비

아래 절차는 별도 네트워크 실행 승인 이후에만 사용한다. 이번 작업에서는 실행하지 않았다.
환경변수는 세션에 안전하게 미리 설정한다. key/실제 Subject 값을 명령어, 문서, Git에 쓰지 않는다.

- `SERPAPI_API_KEY`: 실제 SerpApi key
- `DFSA_LIVE_SUBJECT_JSON`: 허가된 대상자의 name/organization/email JSON
- `--site-url`: 대상자로부터 수집 허가를 받은 하나의 공개 HTTPS 사이트

```powershell
# 승인 후에만 실행. 도메인은 실제 허가된 사이트로 교체한다.
.venv/Scripts/python.exe tests/e2e/live_pipeline.py --live --site-url https://approved.example.org
```

`--live` 없이는 네트워크를 사용하지 않는다. 실행기는 실제 A/B/C를 연결하되 검색 HTTP
요청에 `site:<approved-host>`와 `num=1`을 적용한다. 다른 host의 결과는 HTTP 응답 경계에서
제외하고 Query별 최대 1개 결과만 통과시킨다. SerpApi 호출은 최대 2회, HTML 요청은
redirect hop을 포함해 최대 3회이며 retry/pagination은 없다. `--site-url`의 경로와 관계없이
승인 범위는 그 host 전체다. 단일 페이지만 허용된 경우에는 실행 전에 exact-URL 제한을 추가해야 한다.

B의 URL/redirect/content/body 정책을 유지한다. 각 HTTP hop에서 공개 DNS 답변을 재검증하고,
검증한 IP로 연결을 고정하며 TLS는 원래 hostname으로 검증한다. 내부망/localhost/사설 IP,
다른 host로의 redirect, HTTP downgrade는 차단한다. B의 기존 preflight만으로는 DNS rebinding을
막지 못하므로 Live 전용 transport에서 IP 고정을 추가했다.

출력은 status, 결과 개수, 오류 code, 요청 수만 포함한다. key, Subject, HTML, Exposure,
RiskPath 본문과 원시 예외는 출력하거나 저장하지 않는다. 외부 서비스 오류는 error_codes와
`external_failure`로 기록한다. 정상 0건은 `no_search_results`, `no_exposures`, `no_risk_paths`로
구분한다. 정상 결과의 exit code는 0, 외부 실패/정책 차단/예상 밖 오류는 1, 설정/opt-in 오류는 2다.

## 한계와 /review 중점

- Live 서비스 호환성 및 실제 TLS 연결은 실행하지 않았다. IP 고정은 offline transport 검사만 했다.
- DNS 조회와 전체 수행 시간에 대한 강제 deadline은 없다. HTTP socket timeout은 10초이고
  검색 응답은 1 MiB, HTML은 기존 B의 2 MiB 제한을 적용한다.
- E2E-14는 허용된 외부 경계의 예상 밖 오류를 A/B로 전파시킨다. 외부 의존성이 없고 현재
  항상 success를 반환하는 C에 내부 오류나 failed/partial 응답을 인위적으로 주입하지 않는다.
- `sys.setprofile`은 동기식 현재 thread의 함수 호출을 관찰한다. 향후 비동기/멀티스레드화 시 재검토한다.
- 정량 품질, 실제 웹 전체 레이아웃, JS/PDF/LLM 처리 정확도를 검증하는 테스트가 아니다.
- `/review`: 실제 함수 객체 wiring 및 복구, 모듈 내부를 우회하지 않는 경계, 모든 ID/Evidence와
  C 설명의 보존, 0건/오류/부분 성공 구분, 네트워크 차단, Live host/요청 수/IP 고정/출력 제한,
  기존 CRLF 실패와 미반영 명세 정책을 우선 확인한다.
