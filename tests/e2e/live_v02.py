"""Run approved v0.2 integration checks through one selected stage."""

import argparse
import json
import logging
import os
import re
import sys
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from importlib import import_module
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import quote, quote_plus, unquote_plus

from pydantic import ValidationError

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dfsa.contracts import ExplorationResult, StageStatus, Subject
from dfsa.modules.explorer._types import FetchError
from dfsa.service import orchestrator

from live_v02_transport import LivePolicyError, LiveTransport, PolicyReason, SiteScope

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
_DETAIL_FIELDS = {
    "search": {"searched_at", "queries", "results"},
    "exploration": {"navigation_history", "limit_reached"},
    "profiling": {"sources", "exposures"},
    "analysis": {"personal_profile", "relationship_graph", "phishing_risk_scenarios", "security_recommendations"},
}
_VALIDATION_TYPES = {
    "bool_type", "enum", "extra_forbidden", "greater_than_equal", "int_type", "list_type",
    "literal_error", "missing", "model_type", "string_pattern_mismatch", "string_type", "value_error",
}
_SECRET_NAME = (
    r"(?:(?:serpapi[-_ ])?api[-_ ]?key|(?:access[-_ ]?|refresh[-_ ]?)?token|password|authorization|secret|key)"
)
_SECRET_QUERY = re.compile(r"([?&#])([^=#?&\s]+)=([^&#\s]*)")
_SECRET_ASSIGNMENT = re.compile(
    rf"(?i)(\b{_SECRET_NAME}[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s&,;]+)"
)
_URL_USERINFO = re.compile(r"(https?://)[^/?#\s]+@", re.IGNORECASE)
_AUTH_TOKEN = re.compile(r"\b(Bearer|Basic)\s+[^\s,;]+", re.IGNORECASE)
_HTML_PAGE = re.compile(r"<!doctype\s+html\b|<html(?:\s|>)", re.IGNORECASE)


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


def _diagnostic(error, phase):
    """Keep exception types and metadata on a fixed allowlist."""
    if isinstance(error, LivePolicyError):
        reason = error.reason if isinstance(error.reason, PolicyReason) else PolicyReason.POLICY
        return {"phase": phase, "code": reason.value}
    if isinstance(error, ValidationError):
        kinds = Counter(
            item["type"] if item["type"] in _VALIDATION_TYPES else "other"
            for item in error.errors(include_input=False, include_context=False, include_url=False)
        )
        return {"phase": phase, "code": "contract_validation", "validation_errors": dict(kinds)}
    if isinstance(error, ImportError):
        code = "module_import_error"
    elif isinstance(error, HTTPError) and type(error.code) is int and 100 <= error.code <= 599:
        return {"phase": phase, "code": "http_error", "http_status": error.code}
    elif isinstance(error, TimeoutError) or (isinstance(error, URLError) and isinstance(error.reason, TimeoutError)):
        code = "network_timeout"
    elif isinstance(error, URLError):
        code = "network_error"
    elif phase == "reference_validation" and isinstance(error, ValueError):
        code = "invalid_reference"
    else:
        code = "unexpected_error"
    return {"phase": phase, "code": code}


def _redact_details(data, secrets, original_html):
    if isinstance(data, dict):
        return {key: _redact_details(value, secrets, original_html) for key, value in data.items()}
    if isinstance(data, list):
        return [_redact_details(value, secrets, original_html) for value in data]
    if isinstance(data, str):
        if _HTML_PAGE.search(data):
            return "[HTML omitted]"
        for html in original_html:
            data = data.replace(html, "[HTML omitted]")
        for secret in secrets:
            data = data.replace(secret, "[REDACTED]")
        data = _URL_USERINFO.sub(r"\1[REDACTED]@", data)
        data = _AUTH_TOKEN.sub(r"\1 [REDACTED]", data)
        data = _SECRET_QUERY.sub(
            lambda match: f"{match[1]}{match[2]}=[REDACTED]"
            if re.fullmatch(_SECRET_NAME, unquote_plus(match[2]), re.IGNORECASE) else match[0],
            data,
        )
        return _SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", data)
    return data


def _run(subject, until, transport, *, details=False):
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
    phase = "runner_setup"

    def boundary(stage):
        def call(request):
            nonlocal problem_stage, phase
            # Reaching this callable means existing response and cross-stage
            # validation for all preceding calls has already completed.
            validated.update(responses)
            if stage not in selected:
                raise _StopAtBoundary
            problem_stage = stage
            phase = "module_load"
            function = _load(stage)
            if stage == "search" and not os.environ.get("SERPAPI_API_KEY", "").strip():
                raise _MissingSearchKey
            transport.stage = stage
            start = perf_counter()
            phase = "module_execution"
            try:
                response = function(request)
                returned.add(stage)
                phase = "response_validation"
                return response
            finally:
                transport.stage = None
                reports[stage]["elapsed_ms"] = (perf_counter() - start) * 1000
        return call

    call_stage = orchestrator._call

    def observe(module, request, model):
        nonlocal phase
        response, elapsed = call_stage(module, request, model)
        if isinstance(response, ExplorationResult) and any(
            not transport.scope.contains(document.original_url)
            or not transport.scope.contains(document.final_url) for document in response.documents
        ):
            raise LivePolicyError("An acquired document is outside the approved scope", PolicyReason.PAGE_SCOPE)
        responses[problem_stage] = (response, elapsed)
        phase = "reference_validation"
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
    except LivePolicyError as exc:
        if problem_stage is not None:
            reports[problem_stage]["status"] = "policy_blocked"
            reports[problem_stage]["diagnostic"] = _diagnostic(exc, phase)
        outcome, exit_code = "policy_blocked", 1
    except Exception as exc:
        if problem_stage is not None:
            reports[problem_stage]["status"] = "invalid_response" if problem_stage in returned else "execution_error"
            reports[problem_stage]["diagnostic"] = _diagnostic(exc, phase)
        outcome, exit_code = "execution_error", 1
    finally:
        logging.disable(previous_log_level)

    key = os.environ.get("SERPAPI_API_KEY", "").strip() if details else ""
    secrets = sorted({key, quote(key, safe=""), quote_plus(key)} - {""}, key=len, reverse=True)
    original_html = (
        tuple(document.html_text for document in responses["exploration"][0].documents if document.html_text)
        if details and "exploration" in validated else ()
    )
    for stage in selected:
        if stage in validated:
            response, elapsed = responses[stage]
            if final is not None:
                elapsed = getattr(final.execution_time, f"{stage}_ms")
            reports[stage] = _report_completed(stage, response, elapsed)
            if details:
                payload = response.model_dump(mode="json", include=_DETAIL_FIELDS[stage])
                reports[stage]["details"] = _redact_details(payload, secrets, original_html)
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
    parser.add_argument("--site-url", help="Approved HTTPS page or subtree, required for Explorer and later")
    parser.add_argument("--details", action="store_true", help="Show sensitive stage output in a local terminal")
    args = parser.parse_args(argv)
    if not (args.live and args.consent_confirmed and args.scope_approved):
        print("Live execution requires --live, --consent-confirmed and --scope-approved.")
        return 2
    if args.details and not sys.stdout.isatty():
        print("Detailed output requires a local terminal. Summary output is available without --details.")
        return 2
    try:
        scope = SiteScope(args.site_url) if args.site_url else None
        if scope is None and args.until != "search":
            raise LivePolicyError("Explorer requires an approved HTTPS site")
        subject = Subject.model_validate_json(os.environ["DFSA_V02_LIVE_SUBJECT_JSON"])
    except (KeyError, ValueError, LivePolicyError):
        print("Invalid live configuration. Set the subject environment variable and approved HTTPS scope.")
        return 2

    report, exit_code = _run(subject, args.until, LiveTransport(scope), details=args.details)
    print(json.dumps(report, ensure_ascii=not args.details, indent=2 if args.details else None))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
