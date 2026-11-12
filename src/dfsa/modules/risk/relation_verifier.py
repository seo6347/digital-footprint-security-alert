
"""Evidence-based relation candidate extraction."""

from dataclasses import dataclass

from dfsa.contracts.profiling import Exposure

from .relation_types import (
    RelationType,
    RELATIONS,
    is_valid_relation_pair,
)


RELATION_CUES = (
    "지도교수",
    "소속",
    "재직",
    "담당",
    "지도받",
    "belongs to",
    "supervised by",
    "member of",
    "affiliated with",
)

NEGATION_CUES = (
    "아니다",
    "아니며",
    "아닌",
    "무관",
    "관계없",
    "not affiliated",
    "not supervised",
    "no relation",
)


@dataclass(frozen=True)
class RelationCandidate:
    exposure_id_1: str
    exposure_id_2: str
    source_id: str
    evidence: str
    has_relation_cue: bool
    has_negation_cue: bool
    relation_types: tuple[RelationType, ...] = ()


def normalize_text(text: str) -> str:
    """Normalize whitespace and case for text matching."""
    return " ".join(text.casefold().split())


def extract_relation_candidates(
    exposures: list[Exposure],
) -> list[RelationCandidate]:
    """Find possible relationships supported by shared evidence."""

    candidates = []
    seen = set()

    for i, left in enumerate(exposures):
        for right in exposures[i + 1:]:
            if left.exposure_id == right.exposure_id:
                continue

            left_value = normalize_text(left.value)
            right_value = normalize_text(right.value)

            if not left_value or not right_value:
                continue

            matched_types = tuple(
                relation.relation_type
                for relation in RELATIONS
                if is_valid_relation_pair(
                    relation.relation_type,
                    left.type,
                    right.type,
                )
            )


            right_sources = {
                source.source_id
                for source in right.sources
            }

            for source in left.sources:
                if source.source_id not in right_sources:
                    continue

                evidence_texts = [
                    item.evidence
                    for item in left.sources + right.sources
                    if item.source_id == source.source_id
                ]

                for evidence in evidence_texts:
                    normalized = normalize_text(evidence)

                    if not (
                        left_value in normalized
                        and right_value in normalized
                    ):
                        continue

                    key = (
                        left.exposure_id,
                        right.exposure_id,
                        source.source_id,
                        normalized,
                    )

                    if key in seen:
                        continue

                    seen.add(key)

                    candidates.append(
                        RelationCandidate(
                            exposure_id_1=left.exposure_id,
                            exposure_id_2=right.exposure_id,
                            source_id=source.source_id,
                            evidence=evidence,
                            has_relation_cue=any(
                                cue in normalized
                                for cue in RELATION_CUES
                            ),
                            has_negation_cue=any(
                                cue in normalized
                                for cue in NEGATION_CUES
                            ),
                            relation_types=matched_types,
                        )
                    )

    return candidates

from enum import Enum


class RelationEvidenceStatus(str, Enum):
    SUPPORTED_CANDIDATE = "supported_candidate"
    CONTRADICTED = "contradicted"
    UNCERTAIN = "uncertain"


NEGATIVE_RELATION_PATTERNS = (
    "소속되어 있지 않",
    "소속이 아니",
    "소속이 아니다",
    "소속하지 않",
    "지도교수가 아니",
    "참여하지 않",
    "참석하지 않",
    "관련이 없",
    "관계가 없",
    "사용하지 않",
    "소유하지 않",
    "not affiliated",
    "not supervised",
    "does not belong",
    "does not own",
)


def classify_relation_evidence(
    candidate: RelationCandidate,
) -> RelationEvidenceStatus:
    """Conservatively classify evidence cues for a relation candidate."""

    text = normalize_text(candidate.evidence)

    # Explicit negative patterns take precedence.
    if any(pattern in text for pattern in NEGATIVE_RELATION_PATTERNS):
        return RelationEvidenceStatus.CONTRADICTED

    if candidate.has_negation_cue:
        return RelationEvidenceStatus.CONTRADICTED

    # A keyword is not sufficient to establish a relation.
    if not candidate.has_relation_cue:
        return RelationEvidenceStatus.UNCERTAIN

    # A matched cue provides a positive candidate, not verified support.
    return RelationEvidenceStatus.SUPPORTED_CANDIDATE



from .relation_patterns import get_relation_pattern


def classify_typed_relation(
    candidate: RelationCandidate,
    relation_type: RelationType,
) -> RelationEvidenceStatus:
    """Classify evidence cues for a specific relation type."""

    if relation_type not in candidate.relation_types:
        return RelationEvidenceStatus.UNCERTAIN

    text = normalize_text(candidate.evidence)
    pattern = get_relation_pattern(relation_type)

    # Negative evidence takes precedence.
    if any(cue in text for cue in pattern.negative):
        return RelationEvidenceStatus.CONTRADICTED

    if any(cue in text for cue in pattern.positive):
        return RelationEvidenceStatus.SUPPORTED_CANDIDATE

    return RelationEvidenceStatus.UNCERTAIN

