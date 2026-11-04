"""DFSA service entry point."""

# 외부 애플리케이션이 사용할 Orchestrator 실행 함수를 공개한다.

from .orchestrator import run_pipeline

__all__ = ["run_pipeline"]
