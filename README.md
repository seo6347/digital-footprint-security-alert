# DFSA — Digital Footprint Security Alert

DFSA는 사용자의 공개된 디지털 발자국을 모으고 구조화하여, 여러 정보의 조합이 만들 수 있는 사회공학적 위험과 대응 방안을 설명하는 서비스를 개발하는 팀 프로젝트입니다. 2026학년도 2학기 오픈소스기초설계 수업에서 진행하며, v0.1은 대학교 연구실 구성원이 자신의 공개 정보를 점검하는 상황을 대상으로 합니다.

개발 목표는 공개 정보 검색, 동일인 검증과 근거 보존, 노출 정보 조합에 따른 위험 분석, 이해하기 쉬운 결과 제공입니다. 분석 결과는 실제 공격 성공 확률을 뜻하지 않습니다. 실제 피싱 메일 전송이나 비공개 정보 수집은 제공하지 않으며, 지속 모니터링·알림은 향후 확장 대상입니다.

## 현재 개발 상태

| 영역 | 현재 상태 |
| --- | --- |
| 공통 Contract | Pydantic v2 모델과 validation 테스트 준비 완료 |
| DFSA Orchestrator | 호출 흐름·결과 조합 구현 및 Mock Integration Test 완료 |
| Module A / B / C | 구현·테스트 폴더 준비 완료, 실제 기능 구현 예정 |
| Module별 / E2E Evaluation | 폴더와 안내 문서 준비 완료, Dataset·Metric·절차 미확정 |
| Frontend / UI | 구현 예정 |

현재는 Module 병렬 개발을 시작하기 위한 공통 기반이 준비된 상태입니다. 실제 검색 API, HTML 수집·분석, Risk Rule Engine을 연결한 완성 서비스는 아직 제공하지 않습니다.

## Repository 구조

```text
DFSA/
├── AGENTS.md
├── README.md
├── CONTRIBUTING.md
├── requirements.txt
├── pytest.ini
├── docs/
│   └── team-development-spec-v0.1.md
├── src/dfsa/
│   ├── contracts/                   # 공통 Pydantic Contract
│   ├── service/
│   │   └── orchestrator.py          # Pipeline 실행·결과 조합
│   └── modules/                     # 실제 구현 예정 위치
│       ├── search/                  # Module A
│       ├── profiling/               # Module B
│       └── risk/                    # Module C
├── tests/
│   ├── contract/
│   ├── integration/
│   ├── fixtures/
│   └── modules/                     # Module별 테스트 추가 예정
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

Module 패키지는 현재 빈 `__init__.py`만 포함합니다. Module 테스트와 Evaluation의 빈 디렉터리는 `.gitkeep`으로 유지합니다.

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

기존 Integration Test는 실제 외부 API 대신 Contract-valid Mock을 사용합니다. `pytest.ini`가 테스트 실행 시 `src`를 import 경로에 추가합니다. Module 테스트와 품질 평가 코드는 아직 없습니다. pytest 통과와 Evaluation 완료는 구분합니다.

## Orchestrator 사용 및 Module 연결

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

아래는 함수 구현 후의 연결 예시입니다. `run_search`, `run_profiling`, `run_risk`는 각 담당자의 구현에서 가져올 함수이며, 현재 패키지에는 아직 정의되어 있지 않습니다.

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
| [팀 개발 명세서](docs/team-development-spec-v0.1.md) | v0.1 Architecture·Public Contract·Pipeline 정책의 단일 상세 Source of Truth |
| [Evaluation 안내](evaluation/README.md) | Module별·E2E 평가 위치, 담당, 미결 기준과 데이터 관리 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 팀원 계정·이름 정보 |

상세 Schema·Enum·Risk Rule·상태 정책과 팀 미결 사항은 기술 명세서를 확인합니다. 작업 위치와 수정 범위는 AGENTS.md를, 품질 평가 준비는 Evaluation 안내를 참조하세요.
