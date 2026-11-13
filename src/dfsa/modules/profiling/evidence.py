"""Phase 4 original-span and local attribution validation.

Reuse Phase 3's structural index, not HTML parsing or identity verification.
Rules deliberately accept complete fields, not arbitrary natural language.
Each quote covers adjacent text runs only; inline markup and separate fields
retain separate references and are never joined into a fabricated quotation.
Malformed internal structures raise ValueError. Unsupported/ambiguous evidence
returns an exclusion diagnostic; unexpected implementation errors propagate.
"""

import re
from html import unescape
from urllib.parse import urlsplit

from dfsa.contracts.common import ExposureType, IdentityStatus

from ._types import (
    EvidenceReference, ExposureCandidate, ExtractionDiagnostic, IdentityDecision,
    ParsedDocument, ValidatedExposureCandidate,
)
from .identity import (
    _Document, _EMAIL, _HEADINGS, _NAME, _PAGE, _REGIONS, _chrome,
    _Unit, _name, _normalize, _person, _property,
)

_LABELS = {
    ExposureType.IDENTITY: {"name", "이름", "성명"},
    ExposureType.CONTACT: {"email", "e-mail", "이메일", "전자 우편",
                           "phone", "telephone", "tel", "전화", "전화번호"},
    ExposureType.AFFILIATION: {"affiliation", "organization", "university", "department",
                               "laboratory", "lab", "소속", "대학교", "학과", "연구실"},
    ExposureType.RELATIONSHIP: {"advisor", "supervisor", "지도교수", "collaborator", "공동 연구자"},
    ExposureType.ACTIVITY: {"activity", "project", "presentation", "research activity",
                            "활동", "프로젝트", "발표", "연구 활동"},
    ExposureType.INTEREST: {"research interests", "research interest", "research areas",
                            "연구 관심 분야", "관심 연구 분야"},
    ExposureType.ACCOUNT: {"github", "github account", "github 계정"},
    ExposureType.TEMPORAL: {"project period", "employment period", "education period",
                            "프로젝트 기간", "재직 기간", "재학 기간"},
}
_PHONE_LABELS = {"phone", "telephone", "tel", "전화", "전화번호"}
_RELATIONS = {"advisor": "advisor", "supervisor": "advisor", "지도교수": "advisor",
              "collaborator": "collaborator", "공동 연구자": "collaborator"}
_PHONE = re.compile(r"\+?[0-9][0-9 ()-]{5,24}[0-9]")
_PERIOD = re.compile(r"(?:19|20)\d{2}(?:[-/.](?:0?[1-9]|1[0-2]))?"
                     r"(?:\s*(?:–|—|~|to|부터|-)\s*"
                     r"(?:(?:19|20)\d{2}(?:[-/.](?:0?[1-9]|1[0-2]))?|present|현재))?", re.I)
_GENERIC = {"none", "n/a", "unknown", "없음", "미정", "-"}
_GITHUB_RESERVED = {"about", "apps", "blog", "collections", "contact", "enterprise",
                    "events", "explore", "features", "issues", "join", "login",
                    "marketplace", "new", "notifications", "orgs", "organizations",
                    "pricing", "pulls", "search", "security", "settings", "signup",
                    "site", "sponsors", "topics", "trending"}


def clean(value: str) -> str:
    """Output whitespace normalization; evidence always keeps original case/space."""
    return " ".join(value.split())


def _labeled(raw):
    # An explicitly displayed URL is a value, not a label named "https".
    if raw.strip().startswith("https://"):
        return None
    return re.fullmatch(r"\s*([^:：\n]+)\s*[:：]\s*(.+?)\s*", raw, re.S)


class EvidenceContext:
    """Document-local validation context, shared by discovery and validation."""

    def __init__(self, document: ParsedDocument, identity: IdentityDecision):
        if document.source_id != identity.source_id:
            raise ValueError("Identity source_id does not match document")
        blocks = {b.block_id: b for b in document.blocks}
        if len(blocks) != len(document.blocks):
            raise ValueError("Duplicate block ID")
        # Check before constructing Phase 3's index (which assumes valid paths).
        complete = set()
        for block in document.blocks:
            path = set()
            current = block
            while current is not None and current.block_id not in complete:
                if current.block_id in path:
                    raise ValueError("Cyclic block ancestry")
                path.add(current.block_id)
                if current.parent_id is not None and current.parent_id not in blocks:
                    raise ValueError("Missing parent block")
                current = blocks.get(current.parent_id)
            complete.update(path)
        for text in document.texts:
            if text.block_id not in blocks:
                raise ValueError("Text references missing block")
        self.document = document
        self.identity = identity
        self.tree = _Document(document)
        self.roots = identity.target_block_ids if identity.identity_status == IdentityStatus.CONFIRMED else ()
        if len(set(self.roots)) != len(self.roots):
            raise ValueError("Duplicate target block ID")
        for root in self.roots:
            if type(root) is not int or root not in blocks or blocks[root].tag in _PAGE:
                raise ValueError("Invalid target block ID or page-wide target")
            if any(other != root and self.tree.inside(root, other) for other in self.roots):
                raise ValueError("Overlapping target blocks")
        self.by_index = {i: unit for unit in self.tree.units for i in unit.indices}
        self.attribution_by_index = self.by_index
        self.anchors = {}
        for root in self.roots:
            anchors = []
            for ref in identity.evidence:
                if ref.kind != "name_match":
                    continue
                self.check_indices(ref.text_indices)
                unit = self.by_index.get(ref.text_indices[0])
                if unit is None or ref.block_id != unit.block_id or ref.text_indices != unit.indices:
                    raise ValueError("Invalid identity name reference")
                if _name(unit, self.tree, unit.value) is None:
                    raise ValueError("Identity name reference is not a name field")
                if self.tree.inside(unit.block_id, root) and self.tree.local(unit, root):
                    anchors.append(unit)
            if len(anchors) == 1:
                self.anchors[root] = anchors[0]
        self._safe_roots = {}
        self._addresses = {}
        self.semantic_origins = {}
        self.units, self.semantic_labels = self._field_units()
        self.by_index = {i: unit for unit in self.units for i in unit.indices}

    def _field_units(self):
        """Keep simple inline semantic values separate from surrounding prose.

        The identity tree remains untouched. Nested/multiple properties and
        intervening structural containers are unsupported, never guessed.
        """
        labels = {"name": "name", "email": "email", "telephone": "phone",
                  "affiliation": "affiliation"}
        units = []
        semantic = {}
        for original in self.tree.units:
            groups = {}
            touched = False
            for index in original.indices:
                path = self.tree.paths[self.document.texts[index].block_id]
                local = path[:path.index(original.block_id)]
                owners = [bid for bid in local
                          if (dict(self.tree.blocks[bid].attributes).get("itemprop") or "").split()]
                if not owners:
                    continue
                touched = True
                owner = owners[0]
                props = (dict(self.tree.blocks[owner].attributes).get("itemprop") or "").split()
                if (len(owners) != 1 or len(props) != 1 or props[0] not in labels
                        or any(self.tree.blocks[bid].tag not in {"span", "a", "b", "strong", "em", "i", "small", "label", "code", "mark"}
                               for bid in local)):
                    continue
                groups.setdefault((owner, labels[props[0]]), []).append(index)
            if not touched:
                units.append(original)
                continue
            for (owner, label), indices in groups.items():
                # Do not select a subset of a complex semantic subtree.
                descendants = [i for i in original.indices
                               if self.tree.inside(self.document.texts[i].block_id, owner)]
                if indices != descendants:
                    continue
                unit = _Unit(owner, _normalize("".join(self.document.texts[i].raw_text for i in indices)), tuple(indices))
                units.append(unit)
                semantic[unit] = label
                self.semantic_origins[unit] = original
        return tuple(units), semantic

    def semantic_context_supported(self, unit):
        """Accept bare values or an exact field label, not arbitrary prose.

        A semantic property identifies a type, never the owner. Any remaining
        words beyond a matching field label leave ownership unresolved.
        """
        original = self.semantic_origins[unit]
        first = original.indices.index(unit.indices[0])
        last = original.indices.index(unit.indices[-1])
        prefix = "".join(self.document.texts[i].raw_text for i in original.indices[:first])
        suffix = "".join(self.document.texts[i].raw_text for i in original.indices[last + 1:])
        trim = " \t\r\n:：()[],-"
        label = _normalize(prefix.strip(trim))
        expected = self.semantic_labels[unit]
        allowed = ({"phone": _PHONE_LABELS,
                    "email": _LABELS[ExposureType.CONTACT] - _PHONE_LABELS,
                    "name": _LABELS[ExposureType.IDENTITY],
                    "affiliation": _LABELS[ExposureType.AFFILIATION]})[expected]
        return (not label or label in allowed) and not suffix.strip(trim)

    def check_indices(self, indices):
        if (not indices or any(type(i) is not int or i < 0 or i >= len(self.document.texts)
                               for i in indices)
                or tuple(sorted(set(indices))) != indices):
            raise ValueError("Invalid text indices")

    def safe_root(self, root):
        if root not in self._safe_roots:
            self._safe_roots[root] = self._analyze_root(root)
        return self._safe_roots[root]

    def _analyze_root(self, root):
        tree = self.tree
        if root not in self.anchors or root in tree.ambiguous_lists:
            return False
        if any(_chrome(tree.blocks[bid]) for bid in tree.paths[root]):
            return False
        # Do not borrow fields across nested cards, rows, named lists, sections.
        if any(bid != root and tree.inside(bid, root)
               and (_person(block) or block.tag in _REGIONS or bid in tree.named_lists)
               for bid, block in tree.blocks.items()):
            return False
        # A second name/heading makes field ownership ambiguous. Ordinary
        # section headings are conservatively unsupported here, as in Phase 3.
        names = [unit for unit in tree.units if tree.inside(unit.block_id, root)
                 and (tree.blocks[unit.block_id].tag in _HEADINGS
                      or _NAME.fullmatch(unit.value)
                      or _property(tree.blocks[unit.block_id], "name")
                      or unit.block_id in tree.definition_names)]
        anchor = self.anchors[root]
        return all(unit == anchor for unit in names)

    def references(self, unit):
        """Split at every HTML gap, including inline tags/comments/line breaks."""
        groups = []
        pending = []
        for index in unit.indices:
            text = self.document.texts[index]
            if pending and self.document.texts[pending[-1]].end != text.start:
                groups.append(tuple(pending))
                pending = []
            pending.append(index)
        if pending:
            groups.append(tuple(pending))
        return tuple(EvidenceReference(
            unit.block_id, indices, self.document.texts[indices[0]].start,
            self.document.texts[indices[-1]].end,
            "".join(self.document.texts[i].raw_text for i in indices),
        ) for indices in groups)

    def validate_reference(self, ref, *, attribution=False):
        self.check_indices(ref.text_indices)
        index = self.attribution_by_index if attribution else self.by_index
        unit = index.get(ref.text_indices[0])
        if unit is None or ref.block_id != unit.block_id:
            raise ValueError("Evidence references wrong block")
        if ref not in self.references(unit):
            raise ValueError("Evidence is not an exact contiguous text span")
        previous = ref.start
        for index in ref.text_indices:
            text = self.document.texts[index]
            if (text.start != previous or not 0 <= text.start < text.end <= len(self.document.html_text)
                    or unescape(self.document.html_text[text.start:text.end]) != text.raw_text):
                raise ValueError("Evidence HTML offsets or raw text do not match")
            previous = text.end
        return unit

    def value_reference(self, unit):
        """Select the value's actual location, never a matching word in its label."""
        raw = "".join(self.document.texts[i].raw_text for i in unit.indices)
        match = None if unit in self.semantic_labels else _labeled(raw)
        start, end = match.span(2) if match else (len(raw) - len(raw.lstrip()), len(raw.rstrip()))
        offset = 0
        for ref in self.references(unit):
            next_offset = offset + len(ref.quote)
            if offset <= start < end <= next_offset:
                return ref
            offset = next_offset
        return None

    def field(self, unit):
        """Return explicit label/value and separate label context if present."""
        raw = "".join(self.document.texts[i].raw_text for i in unit.indices)
        if unit in self.semantic_labels:
            return self.semantic_labels[unit], clean(raw), ()
        match = _labeled(raw)
        if match:
            return _normalize(match[1]), clean(match[2]), ()
        # A single dt/dd pair can label a value; no cross-item joins.
        block = self.tree.blocks[unit.block_id]
        if block.tag == "dd":
            siblings = [b for b in self.document.blocks if b.parent_id == block.parent_id]
            position = next(i for i, b in enumerate(siblings) if b.block_id == block.block_id)
            if position and siblings[position - 1].tag == "dt":
                following = siblings[position + 1:position + 2]
                if following and following[0].tag != "dt":
                    return None, clean(raw), ()
                labels = [u for u in self.tree.units if u.block_id == siblings[position - 1].block_id]
                if len(labels) == 1:
                    return labels[0].value.rstrip(":："), clean(raw), self.references(labels[0])
        for prop, label in (("name", "name"), ("email", "email"), ("telephone", "phone"),
                            ("affiliation", "affiliation")):
            if _property(block, prop):
                return label, clean(raw), ()
        return None, clean(raw), ()

    def interpretations(self, unit, root):
        """Finite P0 taxonomy; every value must also have one contiguous quote."""
        if unit in self.semantic_labels and not self.semantic_context_supported(unit):
            return ()
        label, value, context = self.field(unit)
        if not value or _normalize(value) in _GENERIC:
            return ()
        proposals = []
        anchor = self.anchors.get(root)
        if anchor == unit:
            # Recover displayed spelling, never the Subject or normalized name.
            name = value
            if label is None or label in _LABELS[ExposureType.IDENTITY]:
                proposals.append((ExposureType.IDENTITY, name, None))
        if (label in _LABELS[ExposureType.CONTACT] - _PHONE_LABELS or label is None) and _EMAIL.fullmatch(value):
            # Mixed email mentions anywhere in the target prevent automatic
            # ownership, including another person's email in a labeled sentence.
            if root not in self._addresses:
                self._addresses[root] = {m.group().casefold() for u in self.tree.units
                                        if self.tree.inside(u.block_id, root)
                                        for m in _EMAIL.finditer("".join(self.document.texts[i].raw_text for i in u.indices))}
            addresses = self._addresses[root]
            if len(addresses) == 1:
                proposals.append((ExposureType.CONTACT, value, None))
        if label in _PHONE_LABELS and _PHONE.fullmatch(value) and 7 <= sum(c.isdigit() for c in value) <= 15:
            proposals.append((ExposureType.CONTACT, value, None))
        if label in _LABELS[ExposureType.AFFILIATION] or (
            label is None and re.fullmatch(r"[\w .&'()-]+(?:University|대학교)", value, re.I)
        ):
            proposals.append((ExposureType.AFFILIATION, value, None))
        for kind in (ExposureType.RELATIONSHIP, ExposureType.ACTIVITY, ExposureType.INTEREST, ExposureType.TEMPORAL):
            if label in _LABELS[kind] and (kind != ExposureType.TEMPORAL or _PERIOD.fullmatch(value)):
                proposals.append((kind, value, _RELATIONS.get(label) if kind == ExposureType.RELATIONSHIP else None))
        # Only explicitly labeled GitHub fields, never bare external links.
        links = self.document.links if label in _LABELS[ExposureType.ACCOUNT] else ()
        for link in links:
            if not link.text_indices or not set(link.text_indices) <= set(unit.indices):
                continue
            self.check_indices(link.text_indices)
            if (link.block_id not in self.tree.blocks
                    or not all(self.tree.inside(self.document.texts[i].block_id, link.block_id)
                               for i in link.text_indices)
                    or link.text != "".join(self.document.texts[i].raw_text for i in link.text_indices)
                    or dict(link.attributes).get("href") != link.href):
                raise ValueError("Invalid parsed account link reference")
            try:
                if any(ord(char) <= 32 or char.isspace() for char in link.href) or "\\" in link.href:
                    continue
                parts = urlsplit(link.href)
                if (parts.scheme != "https" or parts.netloc.casefold() not in {"github.com", "www.github.com"}
                        or parts.query or parts.fragment):
                    continue
                profile = re.fullmatch(r"/([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)/?", parts.path)
                if profile is None or profile[1].casefold() in _GITHUB_RESERVED:
                    continue
                username = profile[1]
            except ValueError:
                continue
            displayed = clean(link.text)
            if ((value.removeprefix("@").casefold() == username.casefold()
                 and displayed.casefold() in {username.casefold(), "@" + username.casefold()})
                    or displayed == link.href == value):
                proposals.append((ExposureType.ACCOUNT, value, None))
        return tuple((kind, value, relation, context) for kind, value, relation in proposals)


def validate_candidate(
    document: ParsedDocument, identity: IdentityDecision, candidate: ExposureCandidate,
    *, context: EvidenceContext | None = None,
) -> ValidatedExposureCandidate | ExtractionDiagnostic:
    """Validate provenance, attribution, explicit type/value and exact HTML spans.

    Invalid internal references/shape raise ValueError rather than masquerading
    as absent information. Well-formed unsupported proposals are diagnostic.
    """
    ctx = context if context is not None else EvidenceContext(document, identity)
    if ctx.document is not document or ctx.identity is not identity:
        raise ValueError("Evidence context belongs to another input")
    if candidate.source_id != document.source_id:
        raise ValueError("Candidate source_id does not match document")
    if not isinstance(candidate.type, ExposureType) or not candidate.value.strip():
        raise ValueError("Invalid candidate type or empty value")
    unit = ctx.validate_reference(candidate.evidence)
    root = candidate.target_block_id

    def excluded(code):
        return ExtractionDiagnostic(code, candidate.evidence.block_id)

    if root not in ctx.roots or not ctx.tree.inside(unit.block_id, root):
        return excluded("outside_confirmed_scope")
    if not ctx.safe_root(root) or not ctx.tree.local(unit, root):
        return excluded("ambiguous_attribution")
    if (candidate.type, candidate.value, candidate.relation) not in {
        (kind, value, relation) for kind, value, relation, _ in ctx.interpretations(unit, root)
    }:
        return excluded("unsupported_type_or_value")
    if candidate.evidence != ctx.value_reference(unit):
        return excluded("value_not_in_contiguous_evidence")
    # Keep ownership/context separate from the public-ready value quotation.
    attribution = (ctx.references(ctx.anchors[root]) + ctx.field(unit)[2]
                   + tuple(ref for ref in ctx.references(unit) if ref != candidate.evidence))
    if unit in ctx.semantic_origins:
        attribution += ctx.references(ctx.semantic_origins[unit])
    for ref in attribution:
        ctx.validate_reference(ref, attribution=True)
    return ValidatedExposureCandidate(
        candidate.source_id, root, candidate.type, candidate.value,
        candidate.evidence, candidate.relation, attribution,
    )
