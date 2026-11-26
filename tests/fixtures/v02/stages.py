"""Import-safe synthetic fixtures for the v0.2 callable boundaries."""

from datetime import datetime, timezone

from dfsa._documents import ParsedBlock, ParsedDocument, ParsedText
from dfsa.contracts import (
    AnalysisRequest, AnalysisResponse, ErrorDetail, ExplorationRequest, ExplorationResult,
    GraphEdge, GraphNode, NavigationEntry, PersonalProfile, PhishingRiskScenario, ProfileItem,
    ProfilingRequest, ProfilingResponse, QueryExecution, RelationshipGraph, SearchRequest,
    SearchResponse, SearchResult, SecurityRecommendation, Source, Subject,
)

SUBJECT = Subject(name="Sample Researcher", organization="Example University")
STAMP = datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc)
URL = "https://lab.example.org/people/sample"
EVIDENCE = "University: Example University"
HTML = f"<p>{EVIDENCE}</p>"


def stage_requests(request_id="req_fixture", subject=SUBJECT):
    search, exploration, profiling, _ = stage_responses(request_id)
    scope = {"schema_version": "v0.2", "request_id": request_id, "subject": subject}
    return (
        SearchRequest(**scope),
        ExplorationRequest(**scope, search_results=search.results),
        ProfilingRequest(**scope, documents=exploration.documents),
        AnalysisRequest(**scope, exposures=profiling.exposures),
    )


def stage_responses(request_id="req_fixture"):
    scope = {"schema_version": "v0.2", "request_id": request_id, "status": "success"}
    search = SearchResponse(
        **scope, searched_at=STAMP,
        queries=[QueryExecution(
            query_id="q_fixture", text="Sample Researcher Example University",
            provider="synthetic", status="success", input_fields=["name", "organization"],
        )],
        results=[SearchResult(
            source_id="src_profile", url=URL, normalized_url=URL, rank=1,
            relevance={"status": "candidate", "reasons": ["name_match", "organization_match"]},
            discovered_by=[{"query_id": "q_fixture", "provider_rank": 1}],
        )],
    )
    document = ParsedDocument(
        source_id="src_profile", original_url=URL, final_url=URL, encoding="utf-8", html_text=HTML,
        title=None, metadata=(), blocks=(ParsedBlock(0, None, "p", ()),),
        texts=(ParsedText(0, EVIDENCE, EVIDENCE.lower(), 3, 3 + len(EVIDENCE)),), links=(),
    )
    exploration = ExplorationResult(
        **scope, documents=(document,), attempted_source_ids=("src_profile",),
        navigation_history=[NavigationEntry(
            navigation_id="nav_seed", source_id="src_profile", parent_source_id=None,
            root_source_id="src_profile", url=URL, final_url=URL, depth=0, status="success",
        )],
    )
    profiling = ProfilingResponse(
        **scope,
        sources=[Source(source_id="src_profile", url=URL, processing_status="success",
                        identity_status="confirmed")],
        exposures=[{
            "exposure_id": "exp_university", "type": "affiliation", "subtype": "university",
            "value": "Example University", "sources": [{"source_id": "src_profile", "evidence": EVIDENCE}],
        }],
    )
    analysis = AnalysisResponse(
        **scope,
        personal_profile=PersonalProfile(university=[
            ProfileItem(label="University", value="Example University", exposure_ids=["exp_university"]),
        ]),
        relationship_graph=RelationshipGraph(
            nodes=[
                GraphNode(node_id="node_subject", label=SUBJECT.name, kind="person", origin="input",
                          exposure_ids=[]),
                GraphNode(node_id="node_university", label="Example University", kind="university",
                          origin="verified", exposure_ids=["exp_university"]),
            ],
            edges=[GraphEdge(
                edge_id="edge_university", source_node_id="node_subject", target_node_id="node_university",
                relation="AFFILIATED_WITH", exposure_ids=["exp_university"],
            )],
        ),
        phishing_risk_scenarios=[PhishingRiskScenario(
            scenario_id="scenario_affiliation", title="Public affiliation and impersonation",
            explanation="Public organization names can lend credibility to unsolicited requests.",
            educational_example="In a fictional training exercise, a message claims to represent a campus office.",
            exposure_types=["affiliation"], safety_checks=["Verify the request through a known official channel."],
        )],
        security_recommendations=[SecurityRecommendation(
            recommendation_id="rec_verification", title="Verify the sender",
            description="Use an official directory to confirm unexpected requests.", exposure_types=["affiliation"],
        )],
    )
    return search, exploration, profiling, analysis


def mock_handlers(case="success"):
    """Return callables for a documented UI fixture scenario."""
    if case not in {"success", "partial_success", "failed", "zero"}:
        raise ValueError(f"Unknown fixture case: {case}")

    def search(request):
        response = stage_responses(request.request_id)[0]
        if case == "failed":
            query = response.queries[0].model_dump()
            query["status"] = "failed"
            return SearchResponse.model_validate(response.model_dump() | {
                "status": "failed", "results": [],
                "queries": [query],
                "errors": [ErrorDetail(code="MOCK_SEARCH_FAILURE", message="Search unavailable.",
                                       retryable=True, query_id="q_fixture")],
            })
        if case == "zero":
            return SearchResponse.model_validate(response.model_dump() | {"results": []})
        return response

    def exploration(request):
        return stage_responses(request.request_id)[1]

    def profiling(request):
        return stage_responses(request.request_id)[2]

    def analysis(request):
        if case == "partial_success":
            return AnalysisResponse(
                schema_version="v0.2", request_id=request.request_id, status="failed",
                errors=[ErrorDetail(code="MOCK_ANALYSIS_FAILURE", message="Analysis unavailable.",
                                    retryable=True)],
            )
        return stage_responses(request.request_id)[3]

    return {"run_search": search, "run_exploration": exploration,
            "run_profiling": profiling, "run_analysis": analysis}
