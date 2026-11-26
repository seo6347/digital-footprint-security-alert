# DFSA — Digital Footprint Security Alert

DFSA는 사용자의 공개된 디지털 발자국을 모으고 구조화하여, 여러 정보의 조합이 만들 수 있는 사회공학적 위험과 대응 방안을 설명하는 서비스를 개발하는 팀 프로젝트입니다. 2026학년도 2학기 오픈소스기초설계 수업에서 진행하며, v0.1은 대학교 연구실 구성원이 자신의 공개 정보를 점검하는 상황을 대상으로 합니다.

개발 목표는 공개 정보 검색, 동일인 검증과 근거 보존, 노출 정보 조합에 따른 위험 분석, 이해하기 쉬운 결과 제공입니다. 분석 결과는 실제 공격 성공 확률을 뜻하지 않습니다. 실제 피싱 메일 전송이나 비공개 정보 수집은 제공하지 않으며, 지속 모니터링·알림은 향후 확장 대상입니다.

## 현재 개발 상태

v0.1 A/B/C 및 Orchestrator 구현과 Offline E2E가 main에 반영되었다(PR #11). 실제 검색부터 공개 정보 확인까지의 Live E2E 성공은 아직 확인되지 않았다.

v0.2는 팀 Review 대상인 [중앙 개발 명세](docs/team-development-spec-v0.2.md)를 기준으로 다음 기능을 개발한다. 이 문서 변경만으로 v0.2 기능이 구현된 것은 아니다.

| 영역 | v0.2 개발 방향 |
| --- | --- |
| Search | 이름+학교 기반 실제 SerpApi 검색, 이메일 선택 |
| Page Explorer | 승인된 연구실 내 제한적 다중 페이지 탐색 |
| Profiling | Rule + 학교 제공 LLM API, 원문 근거 검증 |
| Analysis | Profile, Relationship Graph, 교육용 사칭 위험 사례, 대응 방안 |
| Orchestrator | 검색·탐색 이력, 단계별 실제 시간, DFSAResult |
| Web UI | 담당자 주도 구현, React + TypeScript + FastAPI 초기 추천 |

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
│   ├── contracts/                   # 공통 Pydantic Contract
│   ├── service/
│   │   └── orchestrator.py          # Pipeline 실행·결과 조합
│   └── modules/                     # v0.1 구현 위치
│       ├── search/                  # Module A
│       ├── profiling/               # Module B
│       └── risk/                    # Module C
├── tests/
│   ├── contract/
│   ├── integration/
│   ├── fixtures/
│   └── modules/                     # Module별 테스트
│       ├── search/
│       ├── profiling/
│       └── risk/
└── evaluation/                      # 품질 평가 준비 위치
    ├── README.md
    ├── module_a/
    ├── module_b/
    ├── module_c/
    └── e2e/
```

위 구조는 현재 v0.1 실행 코드 기준이며 Explorer, Analysis Contract 및 UI는 후속 PR에서 추가/변경한다.

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

기존 Integration Test는 실제 외부 API 대신 Contract-valid Mock을 사용합니다. `pytest.ini`가 테스트 실행 시 `src`를 import 경로에 추가합니다. Module 및 Offline E2E 테스트도 존재한다. v0.2에서는 별도 정량적 Evaluation을 요구하지 않는다.

## Orchestrator 사용 및 Module 연결 (현재 v0.1 코드 기준)

Public entry point는 [src/dfsa/service/orchestrator.py](src/dfsa/service/orchestrator.py)에 있으며, 패키지에서도 import할 수 있습니다.

pytest 밖에서 직접 Python 코드를 실행하려면 Repository root에서 `src`를 import 경로에 포함합니다.

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
```

```python
from dfsa.service import run_pipeline

# Public Interface
# run_pipeline(subject: Subject) -> DFSAResult
```

입력은 공통 `Subject` 모델이고, 반환 값은 공통 `DFSAResult`입니다. Module A/B/C는 서로 직접 호출하지 않으며, Orchestrator가 각 Module의 요청을 만들고 결과를 조합합니다.

각 Module 담당자가 다음 함수를 구현하면 시작 코드에서 연결할 수 있습니다.

| Module | 구현할 함수 | 구현 위치 |
| --- | --- | --- |
| A | `run_search(SearchRequest) -> SearchResponse` | `src/dfsa/modules/search/` |
| B | `run_profiling(ProfilingRequest) -> ProfilingResponse` | `src/dfsa/modules/profiling/` |
| C | `run_risk(RiskRequest) -> RiskResponse` | `src/dfsa/modules/risk/` |

아래는 현재 v0.1 함수 연결 예시입니다. `run_search`, `run_profiling`, `run_risk`는 각 모듈에서 가져올 수 있습니다. v0.2에서는 후속 Contract PR을 통해 Explorer와 run_analysis를 추가/교체합니다.

```python
from dfsa.contracts import Subject
from dfsa.service import orchestrator

# 애플리케이션 시작 시 실제 Module 함수 또는 Mock을 연결한다.
orchestrator.run_search = run_search
orchestrator.run_profiling = run_profiling
orchestrator.run_risk = run_risk

subject = Subject(
    name="홍길동",
    organization="OO대학교",
    email="gildong@univ.ac.kr",
)
result = orchestrator.run_pipeline(subject)
```

연결은 요청 처리 전에 수행합니다. Module이 연결되지 않으면 명시적으로 오류가 발생합니다. 현재 Mock Pipeline 검증은 위 Integration Test 명령으로 실행할 수 있습니다.

## 개발 문서

| 문서 | 역할 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Repository Map, Ownership, 작업 절차와 수정 정책 |
| [v0.2 팀 개발 명세서](docs/team-development-spec-v0.2.md) | 신규 MVP Architecture·Contract·개발 정책 (팀 Review 후 적용) |
| [v0.1 팀 개발 명세서](docs/team-development-spec-v0.1.md) | 기존 구현 및 구조 분리 단계의 계약, 개발 이력 |
| [Evaluation 안내](evaluation/README.md) | v0.1 평가 준비 이력; v0.2는 기능 검증 및 Live E2E 중심 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 팀원 계정·이름 정보 |

상세 Schema·Enum·Risk Rule·상태 정책과 팀 미결 사항은 기술 명세서를 확인합니다. 작업 위치와 수정 범위는 AGENTS.md를, 품질 평가 준비는 Evaluation 안내를 참조하세요.
