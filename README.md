# DFSA — Digital Footprint Security Alert

DFSA는 사용자의 공개된 디지털 발자국을 모으고 구조화하여, 여러 정보의 조합이 만들 수 있는 사회공학적 위험과 대응 방안을 설명하는 서비스를 개발하는 팀 프로젝트입니다. 2026학년도 2학기 오픈소스기초설계 수업에서 진행하며, v0.1은 대학교 연구실 구성원이 자신의 공개 정보를 점검하는 상황을 대상으로 합니다.

개발 목표는 공개 정보 검색, 동일인 검증과 근거 보존, 노출 정보 조합에 따른 위험 분석, 이해하기 쉬운 결과 제공입니다. 분석 결과는 실제 공격 성공 확률을 뜻하지 않습니다. 실제 피싱 메일 전송이나 비공개 정보 수집은 제공하지 않으며, 지속 모니터링·알림은 향후 확장 대상입니다.

## 현재 개발 상태

v0.2 공통 Contract, 네 단계 Orchestrator, 합성 Mock이 준비되어 각 담당자가 독립적으로 개발할 수 있다. v0.1 실제 모듈과 Offline E2E는 기존 동작의 회귀 검증에 사용한다. 실제 검색부터 공개 정보 확인까지의 Live E2E 성공은 아직 확인되지 않았다.

v0.2 개발은 [중앙 개발 명세](docs/team-development-spec-v0.2.md)를 기준으로 한다. Contract Freeze는 [PR #14](https://github.com/seo6347/digital-footprint-security-alert/pull/14)의 팀 승인과 `main` 병합 시 적용한다.

| 영역 | v0.2 구현 상태 및 후속 범위 |
| --- | --- |
| Search | 이름·학교 기반 v0.2 SerpApi 검색 및 예비 관련성 판단 구현 |
| Page Explorer | 승인 범위 내 다중 페이지 탐색, robots 확인, 원문·탐색 이력 보존 구현 |
| Profiling | 문서 입력과 Exposure/Evidence Contract, 학교 LLM Adapter와 합성 파일럿 구현. Rule + LLM 연결은 후속 |
| Analysis | Profile·Graph·교육 사례·대응 방안 Contract 구현. 생성 로직은 후속 |
| Orchestrator | 검색·탐색·Profiling·Analysis 호출 제어, 실행 시간, DFSAResult 구현 |
| Web UI | 합성 DFSAResult 제공. UI 및 API 연결은 후속 |

본인 또는 동의한 대상의 승인된 로컬 시연을 목표로 하며, 실제 피싱 메시지 생성·발송 및 무관한 제3자 개인정보 수집은 제외한다. v0.2에서는 필요에 따라 외부 라이브러리를 활용하고 별도 정량적 Evaluation은 요구하지 않는다.

## Repository 구조

```text
DFSA/
├── AGENTS.md
├── README.md
├── CONTRIBUTING.md
├── requirements.txt
├── pytest.ini
├── docs/
│   ├── team-development-spec-v0.1.md  # 기존 구현/이력
│   └── team-development-spec-v0.2.md  # 신규 개발 명세
├── src/dfsa/
│   ├── _documents.py                # Explorer와 Module B의 공유 내부 문서 자료형
│   ├── contracts/                   # v0.2 공통 Pydantic Contract
│   ├── _v01/                        # 임시 v0.1 계약 및 Orchestrator
│   ├── service/
│   │   └── orchestrator.py          # Pipeline 실행·결과 조합
│   └── modules/                     # 담당자별 구현 및 기존 v0.1 로직
│       ├── search/                  # Module A
│       ├── explorer/                # Page Explorer 문서 확보
│       ├── profiling/               # Module B
│       └── risk/                    # Module C
├── tests/
│   ├── contract/
│   ├── integration/
│   ├── fixtures/v02/                # 단계별 합성 Mock과 UI JSON
│   ├── legacy/                      # v0.1 계약·Orchestrator 회귀 검증
│   ├── e2e/                         # v0.1 실제 모듈 회귀 및 v0.1·v0.2 Live runner
│   └── modules/                     # Module별 테스트
│       ├── search/
│       ├── explorer/                # Fetch, URL Policy, Parsing 회귀 테스트
│       ├── profiling/
│       └── risk/
└── evaluation/                      # v0.1 평가 준비 이력
    ├── README.md
    ├── module_a/
    ├── module_b/
    ├── module_c/
    └── e2e/
```

## 개발 환경 및 설치

Python **3.12**, Pydantic **v2**, pytest를 사용합니다. 공통 의존성은 root [requirements.txt](requirements.txt)에서 관리합니다.

Repository root에서 다음을 실행합니다. 아래 예시는 Windows PowerShell 기준입니다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

가상환경을 활성화하지 않으면 아래 명령의 `python` 대신 `.\.venv\Scripts\python.exe`를 사용할 수 있습니다.

## 테스트 실행

가상환경을 활성화한 뒤 Repository root에서 실행합니다.

```powershell
# 전체 테스트
python -m pytest

# Contract validation 테스트
python -m pytest tests/contract

# Orchestrator Mock Integration Test
python -m pytest tests/integration
```

v0.2 Integration 테스트는 Contract를 만족하는 합성 Mock을 사용합니다. `pytest.ini`는 테스트 실행 시 `src`를 import 경로에 추가합니다. `tests/legacy/`와 `tests/e2e/`의 기존 v0.1 회귀 테스트는 전체 실행에서 계속 검증합니다.

## v0.2 Orchestrator 사용 및 Module 연결

pytest 밖에서 직접 Python 코드를 실행하려면 Repository root에서 `src`를 import 경로에 포함합니다.

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
```

`dfsa.service.run_pipeline(Subject) -> DFSAResult`가 공개 실행 진입점입니다. 요청·응답 모델은 `dfsa.contracts`에서 가져옵니다. 담당자가 후속 PR에서 아래 함수를 구현하면 애플리케이션 시작 시 `dfsa.service.orchestrator`의 같은 이름에 연결합니다.

| 담당 | Public Interface | 구현 예정 파일 / Python 모듈 |
| --- | --- | --- |
| A · 정유채 | `run_search(SearchRequest) -> SearchResponse` | `src/dfsa/modules/search/runner_v2.py` · `dfsa.modules.search.runner_v2` |
| Explorer · 서동균 | `run_exploration(ExplorationRequest) -> ExplorationResult` | `src/dfsa/modules/explorer/runner.py` · `dfsa.modules.explorer.runner` |
| B · 서동균 | `run_profiling(ProfilingRequest) -> ProfilingResponse` | `src/dfsa/modules/profiling/pipeline_v2.py` · `dfsa.modules.profiling.pipeline_v2` |
| C · 강영림 | `run_analysis(AnalysisRequest) -> AnalysisResponse` | `src/dfsa/modules/risk/analysis.py` · `dfsa.modules.risk.analysis` |

연결은 첫 요청 전에 수행합니다. 실행할 단계가 미연결이면 오류가 발생합니다. 저장소 루트에서 아래 예시를 실행하면 합성 Mock만으로 네 단계를 검증할 수 있습니다.

```python
from runpy import run_path
from unittest.mock import patch

from dfsa.service import orchestrator, run_pipeline

fixtures = run_path("tests/fixtures/v02/stages.py")
with patch.multiple(orchestrator, **fixtures["mock_handlers"]("success")):
    result = run_pipeline(fixtures["SUBJECT"])
print(result.model_dump_json(indent=2))
```

`stage_requests()`와 `stage_responses()`는 A → Explorer → B → C 순서의 합성 객체를 반환합니다. Explorer 응답과 B 요청의 내부 문서는 Python 객체로 전달합니다. UI는 아래 JSON을 독립적으로 사용할 수 있습니다. 시간 값은 UI 개발용 합성 예시입니다.

| [UI fixture](tests/fixtures/v02/ui) | 시나리오 |
| --- | --- |
| `success.json` | 네 단계와 8개 결과물이 채워진 정상 흐름 |
| `partial_success.json` | C 실패, 검색·탐색·Exposure 결과 보존 |
| `failed.json` | A 실패, 후속 단계 미실행 |
| `zero.json` | A 정상 0건, 후속 단계 미실행 |

`dfsa._v01`은 기존 실행 및 회귀 검증을 위한 임시 영역입니다. 신규 v0.2 개발은 공개 v0.2 진입점을 사용합니다. 전체 모듈의 v0.2 전환과 회귀 검증 이후 레거시 영역 제거를 검토합니다.

## v0.2 단계별 Live 검증

팀이 대상자의 동의와 사이트·외부 서비스 사용을 승인한 로컬 시연에서만 실행합니다. 승인된 대상의 `name`, `organization`, 선택 `email` JSON은 `DFSA_V02_LIVE_SUBJECT_JSON`에, 검색 키는 기존 `SERPAPI_API_KEY`에 설정합니다. 실제 값은 명령줄이나 저장소 파일에 넣지 않습니다.

```powershell
python tests/e2e/live_v02.py --until search --live --consent-confirmed --scope-approved
python tests/e2e/live_v02.py --until exploration --details --live --consent-confirmed --scope-approved --robots-approved --site-url https://approved.example.org/research/
```

`--until`은 `search`, `exploration`, `profiling`, `analysis` 중 하나입니다. 위 연결 표의 실제 callable을 단계가 필요해질 때 불러옵니다. `analysis`는 전체 Orchestrator를 실행합니다. 중간 단계에서 멈출 때도 같은 Orchestrator의 응답 및 참조 검증을 적용합니다. 미연결 단계에서는 `not_connected`와 필요한 callable을 표시합니다. 정상 0건 등으로 후속 단계 입력이 없으면 `not_started`를 유지합니다.

검색은 승인된 SerpApi에 1회 요청합니다. 실행기는 Module A의 검색어, 요청 파라미터 및 응답을 그대로 전달하므로 승인 사이트 밖의 URL도 검색 결과에서 확인할 수 있습니다.

`--site-url`은 Explorer 이후를 실행할 때 필요합니다. 정확한 HTTPS 호스트의 한 페이지를 지정하고, 경로가 `/`로 끝나면 해당 하위 경로를 포함합니다. 호스트만 지정하면 전체 호스트가 범위가 되며, 승인에는 해당 경로에 필요한 쿼리 변형도 포함됩니다. Explorer가 각 HTTP hop에서 이 범위를 확인하고 공개 DNS 검증, IP 고정 및 원래 호스트의 TLS 검증을 수행합니다. 같은 호스트의 정확한 `/robots.txt`는 별도 승인을 받고 `--robots-approved`로 확인합니다. 확인 불가 또는 redirect된 robots 규칙을 근거로 페이지 요청을 허용하지 않습니다.

Production은 `DFSA_V02_EXPLORER_SCOPE`와 동의·승인 확인 후 설정한 `DFSA_V02_EXPLORER_ROBOTS_APPROVED=1`을 사용합니다. Live Runner는 같은 접근 정책과 HTTPS Transport를 호출합니다. 깊이 3, 페이지 접근 시도 30개, robots 및 redirect를 포함한 HTTP 요청 40회, HTML 2 MiB를 적용합니다. 결과의 방문 수는 요청이 확인된 고유 source ID 수이고, Live 보고서는 HTML 요청과 robots 요청을 따로 표시합니다. 첫 확보 문서와 탐색 경로는 별도로 관리합니다.

실제 요청 후 이미 확보한 URL로 redirect되면 `blocked`(`duplicate_redirect`)로 기록하고 시작 URL의 source ID를 방문 수에 포함합니다. 확보 문서는 한 건만 유지합니다. 이미 확인한 경로를 다시 발견하면 `skipped`로 기록하고 HTTP 요청을 보내지 않습니다.

페이지 단위 10초와 전체 90초 한도를 사용합니다. Explorer는 DNS 결과 대기에 남은 시간을 적용하고 HTTPS 응답 읽기가 지연되면 연결을 종료합니다. 이미 실행 중인 OS DNS 조회나 파서 호출은 즉시 중단할 수 없지만, 기한이 지난 응답은 결과에 포함하지 않으며 후속 요청을 시작하지 않습니다.

A는 기존 `SerpApiProvider`를 사용합니다. Explorer는 승인된 검색 결과를 seed로 사용하며 `uncertain`도 탐색 후보가 됩니다. 링크의 접근 범위와 관련성은 별도로 확인하고 대상의 이름과 조직 문맥을 우선합니다. 개별 프로필은 대상과 연결되는 근거가 있는 링크를 따릅니다. 학교 LLM API 연결은 Module B 개발에서 다룹니다.

기본 JSON은 단계별 상태·시간·건수·분류 및 안전한 오류 코드만 보여줍니다. 실제 내용을 보려면 로컬 터미널에서 `--details`를 지정합니다. 검색어·URL, 탐색 이력, Exposure·Evidence와 C의 분석 결과에 동의 대상의 정보가 포함될 수 있습니다. 상세 출력은 터미널에서만 제공하며 API 키와 URL 자격 증명을 가리고 원문 HTML은 제외합니다. 예외는 발생 단계, 진단 코드, 검증 오류 유형이나 HTTP 상태만 표시합니다.

Explorer 상세 출력의 `document_summaries`에는 확보한 문서별 `source_id`, `original_url`, `final_url`, 제목, 인코딩과 파싱된 텍스트·링크 개수가 표시됩니다.

종료 코드는 정상 실행 또는 정상 0건 0, 실행·정책 오류나 부분 성공 1, 승인·설정 오류 또는 미연결 2입니다.

실제 네트워크를 사용하지 않는 실행기 회귀 검증은 `python -m pytest tests/e2e/test_live_v02.py`로 실행합니다.

## ST3 학교 LLM 합성 파일럿

`dfsa.modules.profiling.llm_adapter.MindlogicSession`은 학교 Gateway의 내부 호출 경계입니다. 기본 모델은 `DFSA_LLM_MODEL`, 생성 토큰 한도는 `DFSA_LLM_MAX_COMPLETION_TOKENS`(기본 4096, 최대 16384)로 설정합니다. 동기 호출자는 `run_sync`에 세션 단위 비동기 작업을 전달하고, 비동기 호출자는 `async with`에서 같은 인터페이스를 사용합니다. 호출별 모델 지정도 가능합니다. ST4·ST5에서 실제 Profiling 연동을 진행합니다.

합성 파일럿 v3은 기본 6개와 복합 2개 사례를 사용합니다. `bilingual-affiliation`은 한글·영문 이름과 여러 문서에 분산된 소속 근거를, `mixed-member-context`는 논문·활동·공용 연락처가 섞인 문서에서 대상자의 정보와 Evidence를 검증합니다. 초기 두 모델은 `gpt-5.4-nano`와 기준 모델 `gpt-5.5`입니다. 같은 `clear-match` 사례를 한 번씩 실행하고 각 호출을 정산한 뒤 `gpt-5.4-mini`, `claude-haiku-5-5`, `gemini-3.8-flash`, `claude-sonnet-5-5`를 확인합니다. 예산과 Schema 호환성이 확인된 모델만 나머지 사례로 확장합니다. 실행 옵션과 사례 목록은 `--help`로 확인합니다.

다음 명령은 비용 없이 대상과 설정만 확인합니다.

```powershell
python tests/e2e/live_llm_pilot.py --model gpt-5.4-nano --case clear-match
```

학교 Dashboard에서 잔액과 파일럿 시작 기준선을 확인한 뒤 유료 호출을 승인합니다. `--verified-call-cap`에는 학교가 확인한 해당 호출의 최대 차감액만 입력합니다. 강제 한도를 확인할 수 없는 경우 아래 `--manual-budget`으로 호출 하나씩 직접 승인할 수 있습니다. 수동 모드에서 실제 차감액은 남은 예산을 넘을 수 있습니다. `--settled-pilot-credits`는 이번 파일럿의 정산 완료 누적액이며 첫 호출에만 0을 사용합니다. 직전 호출의 차감액이 미확정이면 다음 호출을 보류합니다.

```powershell
$env:DFSA_LLM_API_KEY = [System.Net.NetworkCredential]::new(
    '', (Read-Host 'School Gateway API key' -AsSecureString)
).Password
$pilotReport = Join-Path $env:TEMP 'dfsa-st3-nano-clear-match.json'
try {
    python tests/e2e/live_llm_pilot.py --model gpt-5.4-nano --case clear-match `
        --live --manual-budget --settled-pilot-credits 0 |
        Set-Content -Encoding UTF8 -LiteralPath $pilotReport
} finally {
    Remove-Item Env:DFSA_LLM_API_KEY
}
```

파일럿은 전 모델에 생성 토큰 4096과 동일한 Schema를 사용합니다. 보고서의 `score.areas`에는 Identity, Extraction, 정보 귀속, Evidence, Schema별 결과가 나오며, `usage`와 `elapsed_ms`에는 보고된 토큰과 실행 시간이 나옵니다. Timeout도 청구될 수 있습니다. 동일한 Dashboard 범위에서 호출 전후 차감액을 대조하고, 확인된 해당 호출의 실측값만 로컬 JSON의 `actual_credits`에 입력합니다. `credit_source`는 `dashboard` 또는 `gateway_usage`로 표시합니다. 다른 사용량과 분리할 수 없으면 두 값은 `null`로 유지합니다. [학교 사용량 API](https://docs.mindlogic.ai/docs/ssu/api-gateway/reference/usage) · [학교 잔액 API](https://docs.mindlogic.ai/docs/ssu/api-gateway/reference/credits)

`python tests/e2e/live_llm_pilot.py --summarize <보고서1> <보고서2>`는 영역별 통과 건수, 토큰, 중앙 응답 시간과 실측 크레딧을 비교합니다. `case_groups.basic`과 `case_groups.complex`에서 각각 실행한 사례 수와 품질 기준 충족 여부를 확인합니다. 모델 선정은 **전체 8개 사례**에서 Identity 정답과 Schema 통과, 치명적 오류 0건, Evidence가 검증된 필수 Exposure 12건 중 11건 이상(90% 기준)을 요구합니다. Identity가 `confirmed`가 아닌 응답에 Exposure가 있으면 치명적 오류입니다.

전체 품질 기준을 충족하고 정산을 완료한 모델 중 **실측 크레딧 합계가 가장 낮은 단일 모델**을 표시합니다. 크레딧이 같으면 중앙 응답 시간을 비교합니다. 각 모델·사례에 v3 보고서를 하나씩 사용합니다. API 키와 요청·응답 원문은 보고서에 포함되지 않습니다.

### 합성 파일럿 상세 진단

아래 명령은 네트워크 없이 시스템 지시, 합성 입력, JSON Schema와 기대 정답을 보여줍니다.

```powershell
python tests/e2e/live_llm_pilot.py --model gpt-5.4-nano --case clear-match --details
```

API 키를 설정한 뒤 상세 진단 호출을 직접 승인하려면 Dashboard에서 정산한 **이번 파일럿의 누적 사용량**을 입력합니다. 한 번의 호출로 일반 점수와 검증된 구조화 응답을 함께 확인할 수 있습니다.

```powershell
$settled = Read-Host 'Dashboard에서 정산한 파일럿 누적 크레딧'
python tests/e2e/live_llm_pilot.py --model gpt-5.4-nano --case clear-match `
    --live --manual-budget --settled-pilot-credits "$settled" --details
```

`details`에는 기대 정답, 검증된 응답, 정확히 일치하지 않아 누락·추가로 집계된 Exposure, Identity·Evidence 참조의 필드별 차이가 표시됩니다. `possible_representation_difference`는 라벨, 끝 마침표, 대소문자, 공백 등의 차이를 진단합니다. 해당 항목의 `evidence_mismatches`가 비어 있다면 표기 차이와 올바른 근거가 함께 보고된 것입니다. `outside_expected_evidence`는 합성 사례의 기대 근거 범위를 벗어난 참조입니다.

`clear-match`는 지시에서 값을 그대로 복사하도록 하지만, 정답은 `Role:` 같은 라벨과 끝 마침표를 뺀 값이며 Evidence는 전체 원문을 요구합니다. 현재 채점기는 값이 정확히 일치하지 않으면 원문 참조가 정확해도 Attribution과 Evidence를 실패로 집계할 수 있습니다. 상세 진단은 이 차이를 설명하며 v3 지시·입력·Schema·점수는 유지합니다. 이전 요약에는 응답이 없어 상세 진단을 소급할 수 없습니다. 상세 출력은 합성 파일럿에서만 제공하며 검증되지 않은 응답과 API 키는 출력하지 않습니다.

## 개발 문서

| 문서 | 역할 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Repository Map, Ownership, 작업 절차와 수정 정책 |
| [v0.2 팀 개발 명세서](docs/team-development-spec-v0.2.md) | 현재 v0.2 Architecture·Contract·개발 정책 |
| [v0.1 팀 개발 명세서](docs/team-development-spec-v0.1.md) | 기존 구현 및 구조 분리 단계의 계약, 개발 이력 |
| [Evaluation 이력](evaluation/README.md) | v0.1 평가 준비 기록과 v0.2 검증 범위 |
| [v0.1 E2E 안내](tests/e2e/README.md) | 현재 레거시 회귀 실행 경로와 초기 E2E 개발 기록 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 팀원 계정·이름 정보 |

Schema·Enum·상태 정책은 해당 버전의 중앙 명세를, 작업 위치와 수정 범위는 AGENTS.md를 참조하세요.
