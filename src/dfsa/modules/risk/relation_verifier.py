
"""Evidence-based relation candidate extraction."""

from dataclasses import dataclass

from dfsa.contracts.profiling import Exposure


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

            right_sources = {
                source.source_id
                for source in right.sources
            }

            for source in left.sources:
                if source.source_id not in right_sources:
                    continue

                # Either exposure's evidence may contain both values.
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
                        )
                    )

    return candidates

