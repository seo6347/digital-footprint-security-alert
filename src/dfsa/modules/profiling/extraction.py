"""Phase 4 exposure discovery inside confirmed roots; no deduplication or IDs."""

from dfsa.contracts.common import IdentityStatus

from ._types import (
    ExposureCandidate, ExtractionDiagnostic, ExtractionResult, IdentityDecision,
    ParsedDocument, ValidatedExposureCandidate,
)
from .evidence import EvidenceContext, validate_candidate


def extract_exposures(document: ParsedDocument, identity: IdentityDecision) -> ExtractionResult:
    """Return validated internal candidates and expected omission diagnostics.

    Non-confirmed/empty scopes return no candidates. Invalid internal references
    raise ValueError; programming errors propagate. Repeated occurrences remain
    separate and retain their original document order for Phase 5.
    """
    if document.source_id != identity.source_id:
        raise ValueError("Identity source_id does not match document")
    if identity.identity_status != IdentityStatus.CONFIRMED:
        return ExtractionResult()
    if not identity.target_block_ids:
        return ExtractionResult(diagnostics=(ExtractionDiagnostic("missing_target_blocks", -1),))
    ctx = EvidenceContext(document, identity)
    candidates = []
    diagnostics = []
    for root in ctx.roots:
        if not ctx.safe_root(root):
            diagnostics.append(ExtractionDiagnostic("ambiguous_attribution", root))
            continue
        for unit in ctx.units:
            if not ctx.tree.inside(unit.block_id, root) or not ctx.tree.local(unit, root):
                continue
            for kind, value, relation, _ in ctx.interpretations(unit, root):
                ref = ctx.value_reference(unit)
                if ref is None:
                    diagnostics.append(ExtractionDiagnostic("value_not_in_contiguous_evidence", unit.block_id))
                    continue
                proposal = ExposureCandidate(document.source_id, root, kind, value, ref, relation)
                result = validate_candidate(document, identity, proposal, context=ctx)
                if isinstance(result, ValidatedExposureCandidate):
                    candidates.append(result)
                else:
                    diagnostics.append(result)
    return ExtractionResult(tuple(candidates), tuple(diagnostics))
