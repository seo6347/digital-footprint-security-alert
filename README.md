# DFSA — Digital Footprint Security Alert

DFSA는 사용자의 공개된 디지털 발자국을 모으고 구조화하여, 여러 정보의 조합이 만들 수 있는 사회공학적 위험과 대응 방안을 설명하는 서비스를 개발하는 팀 프로젝트입니다. 2026학년도 2학기 오픈소스기초설계 수업에서 진행하며, v0.1은 대학교 연구실 구성원이 자신의 공개 정보를 점검하는 상황을 대상으로 합니다.

개발 목표는 공개 정보 검색, 동일인 검증과 근거 보존, 노출 정보 조합에 따른 위험 분석, 이해하기 쉬운 결과 제공입니다. 분석 결과는 실제 공격 성공 확률을 뜻하지 않습니다. 실제 피싱 메일 전송이나 비공개 정보 수집은 제공하지 않으며, 지속 모니터링·알림은 향후 확장 대상입니다.

## 현재 개발 상태

v0.2 공통 Contract, 네 단계 Orchestrator, 합성 Mock이 준비되어 각 담당자가 독립적으로 개발할 수 있다. v0.1 실제 모듈과 Offline E2E는 기존 동작의 회귀 검증에 사용한다. 실제 검색부터 공개 정보 확인까지의 Live E2E 성공은 아직 확인되지 않았다.

v0.2 개발은 [중앙 개발 명세](docs/team-development-spec-v0.2.md)를 기준으로 한다. Contract Freeze는 [PR #14](https://github.com/seo6347/digital-footprint-security-alert/pull/14)의 팀 승인과 `main` 병합 시 적용한다.

| 영역 | v0.2 구현 상태 및 후속 범위 |
| --- | --- |
| Search | 선택 이메일과 검색 Contract 구현. 실제 v0.2 SerpApi 검색은 후속 |
| Page Explorer | 문서 확보 코드 재사용 가능, 독립 호출 경계 구현. 다중 페이지 탐색은 후속 |
| Profiling | 문서 입력과 Exposure/Evidence Contract 구현. Rule + LLM 처리는 후속 |
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
│   ├── e2e/                         # v0.1 실제 모듈 회귀 및 수동 Live runner
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
