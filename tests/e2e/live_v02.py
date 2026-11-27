"""Run approved v0.2 integration checks through one selected stage."""

import argparse
import json
import logging
import os
import sys
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from importlib import import_module
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dfsa.contracts import ExplorationResult, SearchResponse, StageStatus, Subject
from dfsa.modules.explorer._types import FetchError
from dfsa.service import orchestrator

from live_v02_transport import LivePolicyError, LiveTransport, SiteScope

MODULES = {
    "search": "dfsa.modules.search.runner_v2",
    "exploration": "dfsa.modules.explorer.runner",
    "profiling": "dfsa.modules.profiling.pipeline_v2",
    "analysis": "dfsa.modules.risk.analysis",
}
STAGES = tuple(MODULES)
ERROR_CODES = frozenset(
    {"SEARCH_API_KEY_MISSING", "SEARCH_AUTH_ERROR", "SEARCH_LIMIT_ERROR", "SEARCH_HTTP_ERROR",
     "SEARCH_TIMEOUT", "SEARCH_NETWORK_ERROR", "SEARCH_INVALID_RESPONSE", "SEARCH_API_ERROR"}
    | {kind.value for kind in FetchError}
)


class _StopAtBoundary(Exception):
    """The preceding stage was validated by Orchestrator."""


class _NotConnected(Exception):
    """The v0.2 module or its expected callable is absent."""


class _MissingSearchKey(Exception):
    """Only checked once an actual search callable is available."""


class _LiveParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid live runner arguments. Use --help.\n")


def _load(stage):
    path = MODULES[stage]
    try:
        module = import_module(path)
    except ModuleNotFoundError as exc:
        if exc.name and (path == exc.name or path.startswith(exc.name + ".")):
            raise _NotConnected from None
        raise
    function = getattr(module, f"run_{stage}", None)
    if not callable(function) or function is orchestrator._not_connected:
        raise _NotConnected
    return function


def _counts(items, field):
    return dict(Counter("pending" if value is None else value.value
                        for value in (getattr(item, field) for item in items)))


def _output(stage, response):
    if stage == "search":
        return {"queries": _counts(response.queries, "status"), "discovered_sources": len(response.results)}
    if stage == "exploration":
        return {
            "documents": len(response.documents), "navigation": _counts(response.navigation_history, "status"),
            "visited_pages": len(set(response.attempted_source_ids)), "limit_reached": response.limit_reached,
        }
    if stage == "profiling":
        return {
            "sources": _counts(response.sources, "processing_status"),
            "identity_decisions": _counts(response.sources, "identity_status"),
            "exposures": _counts(response.exposures, "type"),
        }
    return {
        "has_profile": response.personal_profile is not None,
        "graph_nodes": len(response.relationship_graph.nodes), "graph_edges": len(response.relationship_graph.edges),
        "scenarios": len(response.phishing_risk_scenarios), "recommendations": len(response.security_recommendations),
    }


def _report_completed(stage, response, elapsed):
    return {
        "status": response.status.value, "elapsed_ms": elapsed, "output": _output(stage, response),
        "errors": [
            {"code": error.code if error.code in ERROR_CODES else "MODULE_ERROR", "retryable": error.retryable}
            for error in response.errors
        ],
    }


def _run(subject, until, transport):
    selected = STAGES[:STAGES.index(until) + 1]
    reports = {
        stage: {"status": "not_started" if stage in selected else "out_of_scope", "elapsed_ms": None}
        for stage in STAGES
    }
    responses = {}
    validated = set()
    returned = set()
    problem_stage = None
    final = None
    outcome = "completed"
    exit_code = 0

    def boundary(stage):
        def call(request):
            nonlocal problem_stage
            # Reaching this callable means existing response and cross-stage
            # validation for all preceding calls has already completed.
            validated.update(responses)
            if stage not in selected:
                raise _StopAtBoundary
            problem_stage = stage
            function = _load(stage)
            if stage == "search" and not os.environ.get("SERPAPI_API_KEY", "").strip():
                raise _MissingSearchKey
            transport.stage = stage
            start = perf_counter()
            try:
                response = function(request)
                returned.add(stage)
                return response
            finally:
                transport.stage = None
                reports[stage]["elapsed_ms"] = (perf_counter() - start) * 1000
        return call

    call_stage = orchestrator._call

    def observe(module, request, model):
        response, elapsed = call_stage(module, request, model)
        if isinstance(response, SearchResponse) and any(
            not transport.scope.contains(item.url) for item in response.results
        ):
            raise LivePolicyError("Search returned a source outside the approved scope")
        if isinstance(response, ExplorationResult) and any(
            not transport.scope.contains(document.original_url)
            or not transport.scope.contains(document.final_url) for document in response.documents
        ):
            raise LivePolicyError("An acquired document is outside the approved scope")
        responses[problem_stage] = (response, elapsed)
        return response, elapsed

    start = perf_counter()
    previous_log_level = logging.root.manager.disable
    try:
        logging.disable(sys.maxsize)
        with open(os.devnull, "w", encoding="utf-8") as discarded, \
                redirect_stdout(discarded), redirect_stderr(discarded), transport.install(), \
                patch.multiple(orchestrator, _call=observe,
                               **{f"run_{stage}": boundary(stage) for stage in STAGES}):
            final = orchestrator.run_pipeline(subject)
        validated.update(responses)
        if final.status.value != "success":
            outcome = final.status.value
            exit_code = 1
        elif getattr(final.stages, until) == StageStatus.NOT_STARTED:
            outcome = "no_input_for_next_stage"
    except _StopAtBoundary:
        outcome = "reached_requested_stage"
    except _NotConnected:
        reports[problem_stage]["status"] = "not_connected"
        outcome, exit_code = "not_connected", 2
    except _MissingSearchKey:
        reports[problem_stage]["status"] = "missing_search_key"
        outcome, exit_code = "missing_search_key", 2
    except LivePolicyError:
        if problem_stage is not None:
            reports[problem_stage]["status"] = "policy_blocked"
        outcome, exit_code = "policy_blocked", 1
    except Exception:
        if problem_stage is not None:
            reports[problem_stage]["status"] = "invalid_response" if problem_stage in returned else "execution_error"
        outcome, exit_code = "execution_error", 1
    finally:
        logging.disable(previous_log_level)

    for stage in selected:
        if stage in validated:
            response, elapsed = responses[stage]
            if final is not None:
                elapsed = getattr(final.execution_time, f"{stage}_ms")
            reports[stage] = _report_completed(stage, response, elapsed)
            if response.errors or response.status.value != "success":
                exit_code = exit_code or 1

    report = {
        "until": until, "outcome": outcome, "stage": problem_stage if outcome in {
            "not_connected", "missing_search_key", "policy_blocked", "execution_error",
        } else None,
        "pipeline_status": final.status.value if final is not None else None,
        "elapsed_ms": (perf_counter() - start) * 1000,
        "stages": reports,
        "search_requests": transport.search_requests, "html_requests": transport.html_requests,
    }
    if outcome == "not_connected":
        report["expected_callable"] = f"{MODULES[problem_stage]}.run_{problem_stage}"
    return report, exit_code


def main(argv=None):
    parser = _LiveParser(description=__doc__)
    parser.add_argument("--until", choices=STAGES, required=True)
    parser.add_argument("--live", action="store_true", help="Explicitly enable live execution")
    parser.add_argument("--consent-confirmed", action="store_true", help="Confirm target consent")
    parser.add_argument("--scope-approved", action="store_true", help="Confirm approval of site and providers")
    parser.add_argument("--site-url", help="Approved HTTPS page or subtree (trailing slash)")
    args = parser.parse_args(argv)
    if not (args.live and args.consent_confirmed and args.scope_approved):
        print("Live execution requires --live, --consent-confirmed and --scope-approved.")
        return 2
    try:
        scope = SiteScope(args.site_url or "")
        subject = Subject.model_validate_json(os.environ["DFSA_V02_LIVE_SUBJECT_JSON"])
    except (KeyError, ValueError, LivePolicyError):
        print("Invalid live configuration. Set the subject environment variable and approved HTTPS scope.")
        return 2

    report, exit_code = _run(subject, args.until, LiveTransport(scope))
    print(json.dumps(report, ensure_ascii=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
