"""Local development HTTP API for DFSA. Does not modify orchestrator.py."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from dfsa.contracts import DFSAResult, Subject
from dfsa.service import orchestrator


def configure_modules() -> None:
    """Connect Modules A, B, and C to the orchestrator."""
    from dfsa.modules.search import run_search
    from dfsa.modules.profiling import run_profiling
    from dfsa.modules.risk.engine import run_risk

    orchestrator.run_search = run_search
    orchestrator.run_profiling = run_profiling
    orchestrator.run_risk = run_risk


def create_app(*, configure: bool = True) -> FastAPI:
    # Tests may inject contract-valid module mocks and disable real wiring.
    if configure:
        configure_modules()

    app = FastAPI(title="DFSA Local API", version="0.1.0")

    @app.middleware("http")
    async def disable_response_caching(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health():
        connected = {
            "search": orchestrator.run_search is not orchestrator._not_connected,
            "profiling": orchestrator.run_profiling is not orchestrator._not_connected,
            "risk_analysis": orchestrator.run_risk is not orchestrator._not_connected,
        }
        return {"ready": all(connected.values()), "modules": connected}

    @app.post("/api/analyze", response_model=DFSAResult)
    def analyze(subject: Subject):
        print("[DFSA] analyze 진입", flush=True)
        # This endpoint promises the full pipeline. Never simulate a missing C.
        if any(
            runner is orchestrator._not_connected
            for runner in (
                orchestrator.run_search,
                orchestrator.run_profiling,
                orchestrator.run_risk,
            )
        ):
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "PIPELINE_NOT_READY",
                    "message": "분석 모듈 연결이 완료되지 않았다.",
                },
            )
            
        try:
            print("[DFSA] 파이프라인 시작", flush=True)
            result = orchestrator.run_pipeline(subject)
            print("[DFSA] 파이프라인 종료", flush=True)
            return result
        except Exception as exc:
            print(f"[DFSA] 파이프라인 예외: {type(exc).__name__}", flush=True)
            return JSONResponse(
                status_code=500,
                content={
                    "detail": {
                        "code": "ANALYSIS_FAILED",
                        "message": "분석 처리 중 서버 오류가 발생했다.",
                    }
                },
            )


    frontend_dir = Path(__file__).resolve().parents[3] / "frontend"

    if not (frontend_dir / "index.html").is_file():
        raise RuntimeError(
            f"index.html을 찾을 수 없다: {frontend_dir / 'index.html'}"
        )

    # 모든 API 경로를 등록한 후 마지막에 정적 파일 경로를 등록한다.
    app.mount(
        "/",
        StaticFiles(directory=str(frontend_dir), html=True),
        name="frontend",
    )

    return app

