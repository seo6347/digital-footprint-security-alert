# DFSA Repository 작업 가이드

이 문서는 DFSA Repository에서 개발자와 Coding Agent가 **어디를 수정할 수 있는지, 어떤 규칙을 따라야 하는지, 어떤 문서를 확인해야 하는지** 빠르게 판단하기 위한 가이드이다.

상세 기술 명세나 구현 설명서를 대체하지 않는다.

---

## 1. Source of Truth

v0.1의 Architecture, Public Contract, Schema, Data Flow, Module 책임, Pipeline 정책의 기준은 다음 문서이다.

`docs/team-development-spec-v0.1.md`

* README는 프로젝트 소개용이다.
* CONTRIBUTING은 팀원 정보 관리용이다.
* 상세 개발 결정은 `team-development-spec-v0.1.md`를 따른다.
* 코드와 명세가 명백하게 충돌하면 임의로 수정하지 말고 먼저 보고한다.

현재는 상세 명세를 하나의 파일로 유지한다.

향후 Module별 내부 설계가 커지면 문서 분리를 검토할 수 있지만, 그 전까지 `team-development-spec-v0.1.md`가 단일 상세 Source of Truth이다.

---

## 2. 수정 정책

| 정책             | 의미                            | 작업 기준                                  |
| -------------- | ----------------------------- | -------------------------------------- |
| 🟢 자유 수정       | 담당 Component의 내부 구현           | Public Contract와 명세를 지키는 범위에서 Owner 재량 |
| 🟡 담당 영역       | 특정 Owner가 관리하는 영역             | 다른 담당자가 수정하려면 Owner와 먼저 협의             |
| 🔴 공통 Contract | 여러 Component가 공유하는 Public API | 팀 합의 없이 누구도 임의 변경 금지                   |

### 기본 원칙

* 🟡 영역도 해당 Owner에게는 내부 구현 범위에서 🟢로 본다.
* 🔴 영역은 Owner 여부와 관계없이 팀 합의 없이 변경하지 않는다.
* 내부 구현 자율성은 Public field, Enum, required/optional, ID 구조, Public Interface 변경까지 포함하지 않는다.
* 테스트나 fixture를 완화해서 잘못된 Schema를 통과시키지 않는다.
* 명세에 없는 공통 영역에 임의로 Owner를 지정하지 않는다.

### 🔴 영역 변경이 필요한 경우

먼저 다음을 정리해 보고한다.

1. 변경이 필요한 이유
2. 영향받는 Component
3. 예상 변경 파일
4. Public Contract 영향

이미 팀에서 합의된 변경이라면 합의된 범위 안에서만 수정한다.

---

## 3. Repository Map

작은 helper나 단순 test 파일은 모두 나열하지 않는다.
주요 책임, Public Contract, Component 진입점처럼 다른 작업에 영향을 주는 파일만 관리한다.

| Path                                 | 역할 / 수정 시점                                            | 정책       |
| ------------------------------------ | ----------------------------------------------------- | -------- |
| `AGENTS.md`                          | Repository 구조, Ownership, 수정 정책, Agent 작업 방식이 바뀔 때 갱신 | 🟡       |
| `docs/team-development-spec-v0.1.md` | Architecture, Contract, 책임, Pipeline 등 팀 공통 결정 관리     | 🔴       |
| `README.md`                          | 프로젝트 소개 및 주요 문서 안내                                    | 🟡       |
| `CONTRIBUTING.md`                    | 팀원 계정·이름 등 협업 정보 관리                                   | 🟡       |
| `src/dfsa/`                          | DFSA Python 패키지 루트                                    | 하위 정책 적용 |
| `src/dfsa/__init__.py`               | 패키지 초기화                                               | 🟡       |
| `src/dfsa/contracts/`                | A/B/C, Orchestrator, UI가 공유하는 Pydantic Contract       | 🔴       |
| `src/dfsa/contracts/__init__.py`     | Public Contract import/export 진입점                     | 🔴       |
| `src/dfsa/contracts/common.py`       | 공통 모델, Subject, ErrorDetail, Enum                     | 🔴       |
| `src/dfsa/contracts/search.py`       | Module A 요청·응답 Contract                               | 🔴       |
| `src/dfsa/contracts/profiling.py`    | Module B 요청·응답, Source·Exposure Contract              | 🔴       |
| `src/dfsa/contracts/risk.py`         | Module C 요청·응답, RiskPath·Evaluation Contract          | 🔴       |
| `src/dfsa/contracts/result.py`       | 최종 `DFSAResult`, stage, summary Contract              | 🔴       |
| `src/dfsa/modules/`                  | 실제 Module Python 패키지 루트; 하위 담당 영역별 작업 위치 | 하위 정책 적용 |
| `src/dfsa/modules/search/`           | Module A 구현 위치 — 정유채 담당                         | 🟡       |
| `src/dfsa/modules/profiling/`        | Module B 구현 위치 — 서동균 담당                         | 🟡       |
| `src/dfsa/modules/risk/`             | Module C 구현 위치 — 강영림 담당                         | 🟡       |
| `src/dfsa/service/`                  | 서동균 담당 상위 Pipeline service                         | 🟡       |
| `src/dfsa/service/__init__.py`       | Public `run_pipeline` import 진입점                      | 🟡       |
| `src/dfsa/service/orchestrator.py`   | 요청 변환, 호출·상태 제어, 오류·결과 조합 및 Module callable 연결 | 🟡       |
| `tests/contract/`                    | Public Contract validation 회귀 테스트                     | 🟡       |
| `tests/integration/`                 | Contract-valid Mock 기반 Orchestrator Pipeline 검증       | 🟡       |
| `tests/modules/search/`              | Module A 동작·오류 처리 테스트 위치 — 정유채 담당          | 🟡       |
| `tests/modules/profiling/`           | Module B 동작·오류 처리 테스트 위치 — 서동균 담당          | 🟡       |
| `tests/modules/risk/`                | Module C 동작·오류 처리 테스트 위치 — 강영림 담당          | 🟡       |
| `tests/fixtures/`                    | Contract 기준 Mock JSON                                 | 🟡       |
| `evaluation/README.md`               | tests와 Evaluation의 구분, 담당·미결 기준·데이터 관리 안내 | 🟡       |
| `evaluation/module_a/`               | Module A 품질 평가 위치 — 정유채 담당                    | 🟡       |
| `evaluation/module_b/`               | Module B 품질 평가 위치 — 서동균 담당                    | 🟡       |
| `evaluation/module_c/`               | Module C 품질 평가 위치 — 강영림 담당                    | 🟡       |
| `evaluation/e2e/`                    | E2E 품질 평가 위치 — 팀 공동 협의, 단독 Owner 미확정      | 🟡       |
| `pytest.ini`                         | pytest 탐색 및 import 설정                                 | 🟡       |
| `requirements.txt`                   | 공통 Python dependency 관리                               | 🟡       |
| `.gitignore`                         | 캐시·로컬 환경·민감 파일 제외 설정                                  | 🟡       |

Contract가 변경되면 관련 `tests/contract/`와 `tests/fixtures/`도 함께 확인한다.

---

## 4. 아직 구현되지 않은 영역

아래는 아직 기능 구현이 없는 영역이다. Module A/B/C의 패키지와 테스트·평가 폴더는 준비되어 있지만 실행 entry point나 실제 구현은 없다.

| 영역               | 현재 상태 | 정책                          |
| ---------------- | ----- | --------------------------- |
| Module A         | 폴더·패키지만 준비, 구현 전 | 🟡 정유채 담당 / 내부 구현은 Owner 재량 |
| Module B         | 폴더·패키지만 준비, 구현 전 | 🟡 서동균 담당 / 내부 구현은 Owner 재량 |
| Module C         | 폴더·패키지만 준비, 구현 전 | 🟡 강영림 담당 / 내부 구현은 Owner 재량 |
| Evaluation       | 폴더만 준비, Dataset / Metric / 절차 미확정 | 🟡 각 Module 담당 / E2E는 팀 협의 |
| Frontend / UI    | 구현 전  | 🟡 정유채 담당 / 내부 구현은 Owner 재량 |

구현이 추가되면 실제 경로와 주요 entry point를 Repository Map에 반영한다.

---

## 5. Ownership

| 영역            | Owner          | 책임 요약                                               |
| ------------- | -------------- | --------------------------------------------------- |
| Module A      | 정유채            | 공개 정보 검색·수집 및 후보 관련성 판단                             |
| Frontend / UI | 정유채            | 사용자 입력 및 최종 결과 표시                                   |
| Module B      | 서동균            | 동일인 검증, Exposure 추출·검증, Source/Evidence 관리          |
| Module C      | 강영림            | Risk 분석, RiskPath 생성, 평가, reason·recommendations 생성 |
| Orchestrator  | 서동균            | A → B → C 호출 제어, 상태 관리, 실패 전파, 결과 조합                |
| 공통 Contract   | 서동균 + 팀 Review | Public Contract 관리 및 변경 검토                          |

### Component 간 핵심 규칙

* A/B/C는 서로 직접 호출하지 않는다.
* Orchestrator가 Public Interface를 통해 전체 흐름을 관리한다.
* `reason`, `recommendations` 등 Risk 설명 생성은 Module C 책임이다.
* Orchestrator는 C의 설명을 새로 생성하거나 수정하지 않는다.
* Module C의 template 우선 / LLM fallback 및 미결 정책은 상세 명세를 따른다.

---

## 6. Spec Lookup Guide

큰 작업을 시작할 때 `team-development-spec-v0.1.md` 전체를 매번 읽을 필요는 없다.

다음 순서로 확인한다.

1. `AGENTS.md` 확인
2. 작업 영역과 Owner 확인
3. 상세 명세에서 관련 heading / keyword 검색
4. 필요한 섹션만 읽기
5. 작업 수행

| 작업             | 우선 확인할 명세                                                                    |
| -------------- | ---------------------------------------------------------------------------- |
| 전체 범위·책임       | §1 문서 목적, §2 프로젝트 범위, §3 Component 및 담당 범위                                   |
| Module A       | §3.1, §9 SearchRequest, §10 SearchResponse                                   |
| Module B       | §3.2, §11 ProfilingRequest, §12~17 Identity / Exposure / Source              |
| Module C       | §3.3, §18 RiskRequest, §19~22 Risk Rule / Status / Evaluation / RiskResponse |
| Orchestrator   | §3.4, §23 DFSAResult, §24 Pipeline 제어, §25 Public Interface                  |
| Contract 변경    | 해당 Schema, §6~8 공통 규칙, §26~29 Contract 관련 규칙                                 |
| Test / Fixture | 해당 Contract, §27 Validation, §30 Mock Data, §35 Merge 조건                     |
| Integration    | §25 Public Interface, §32 Integration 순서                                     |
| UI             | §23 Service → UI, §37 UI Contract                                            |
| 개발 순서 / 완료 조건  | §31, §32, §34, §36                                                           |
| Evaluation     | §39 Evaluation 계획 및 미결 사항, `evaluation/README.md`                         |

Evaluation의 Dataset, Metric, 절차처럼 아직 확정되지 않은 내용은 임의로 결정하지 않는다.

영향 범위가 여러 Component에 걸리면 해당 Component 섹션과 공통 규칙을 함께 확인한다.

---

## 7. Agent Workflow

큰 작업은 다음 순서로 진행한다.

1. `AGENTS.md`와 현재 branch / working tree를 확인한다.
2. 기존 사용자 변경사항을 보존한다.
3. 작업 대상 Path와 🟢/🟡/🔴 정책을 확인한다.
4. 관련 명세 섹션만 찾아 읽는다.
5. 요청 범위와 현재 개발 단계를 확인한다.
6. 이후 Phase의 구현을 요청 없이 미리 시작하지 않는다.
7. 🔴 변경 필요, 명세 충돌, 미결 사항을 발견하면 먼저 보고한다.
8. 승인된 범위에서 구현한다.
9. 관련 테스트를 실행한다.
10. 필요한 경우 Documentation Update Policy에 따라 문서를 갱신한다.
11. 변경 내용, 테스트 결과, 남은 미결 사항을 보고한다.

PR 본문은 기술 명세의 `What / Why / Test` 형식을 따른다.

---

## 8. 테스트 및 검증

기본 환경:

* Python 3.12
* Pydantic v2
* pytest

기본 전체 테스트:

```bash
python -m pytest
```

Contract 테스트만 실행:

```bash
python -m pytest tests/contract
```

Windows 로컬 환경에서는 필요하면 다음을 사용할 수 있다.

```bash
.venv\Scripts\python.exe -m pytest
```

문서만 변경한 경우에는 테스트 실행이 필수가 아닐 수 있다. 대신 다음을 확인한다.

* 실제 Path와 문서 내용 일치 여부
* Ownership 일치 여부
* 명세 참조 정확성
* 변경 diff

테스트를 실행하지 않았다면 그 이유를 최종 보고에 남긴다.

---

## 9. Documentation Update Policy

모든 코드 변경마다 문서를 수정하지 않는다.

### `AGENTS.md`를 갱신하는 경우

* 주요 폴더 또는 파일 추가·삭제
* 주요 파일의 책임 변경
* Component entry point 변경
* Ownership 변경
* 수정 정책 변경
* Agent 작업 방식 변경

작은 helper, 단순 test, 내부 refactoring은 일반적으로 반영하지 않는다.

### `team-development-spec-v0.1.md`를 갱신하는 경우

* Public Contract 변경
* Schema / Enum 변경
* Public Interface 변경
* Architecture / Data Flow 변경
* Module 책임 변경
* Pipeline 정책 변경
* 상태 / Error 처리 정책 변경
* 팀 공통 결정 변경

내부 구현 방식, helper 함수, 변수명 변경 등은 일반적으로 상세 명세 대상이 아니다.

Contract 관련 변경은 명세의 Contract 변경 절차를 따른다.

---

## 10. 문서 유지 원칙

`AGENTS.md`는 상세 구현 설명서가 아니다.

다음 원칙을 유지한다.

* 가능한 한 짧게 유지한다.
* Schema 전체를 복사하지 않는다.
* 함수 내부 알고리즘을 설명하지 않는다.
* 상세 정책을 중복 정의하지 않는다.
* Repository 구조와 작업 규칙을 빠르게 찾는 용도로 유지한다.

---

## 11. 향후 문서 분리

현재는 `team-development-spec-v0.1.md` 하나를 중앙 상세 명세로 유지한다.

다음 상황이 생기면 Module별 문서 분리를 검토한다.

* Module 내부 설계가 크게 증가함
* 특정 Module 작업을 위해 무관한 내용을 지나치게 많이 탐색해야 함
* Algorithm / Provider / Evaluation 등 별도 상세 문서가 필요함
* 하나의 명세 파일에서 동시 편집 충돌이 잦아짐
* 공통 Contract와 Module 내부 설계를 분리할 필요가 생김

분리 이후에도 다음 항목은 가능한 한 중앙 명세에 유지한다.

* Architecture
* Public Contract
* Common Enum
* Data Flow
* Public Interface
* ID Ownership
* Pipeline 상태 규칙
* Contract 변경 정책

Module별 문서에는 내부 구현과 상세 설계를 둔다.

문서를 실제로 분리할 때는 `AGENTS.md`의 Repository Map과 참조 경로도 함께 갱신한다.
