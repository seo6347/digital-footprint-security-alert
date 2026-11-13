"""Conservative static identity rules, without network, LLM or extraction.

P0 supports standalone heading/name fields in bounded cards, rows and items.
Names and university names use NFC, casefold and collapsed whitespace, never
aliases, transliteration or substring matching. Emails match visible complete
addresses (case-insensitively), without plus/dot/domain-only equivalence.

A class or a heading alone does not establish ownership. A region must have one
name anchor and local independent fields, with no nested person regions, shared
chrome or intervening containers joining otherwise unrelated fields. Ambiguous
or unsupported layouts remain uncertain. Returned roots are document-local and
must not be widened by callers. Phase 4 still has to validate each attribution.
"""

import re
import unicodedata
from dataclasses import dataclass

from dfsa.contracts.common import IdentityStatus, Subject

from ._types import IdentityDecision, IdentityEvidence, ParsedBlock, ParsedDocument

_INLINE = {"span", "a", "b", "strong", "em", "i", "small", "label", "code", "mark"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_REGIONS = {"div", "section", "article", "li", "tr"}
_PAGE = {"document", "html", "body", "main"}
_CHROME = {"footer", "nav", "aside", "form", "head"}
_CARDS = {"card", "profile", "profile-card", "person", "person-card", "member",
          "member-card", "faculty", "faculty-card"}
_NAME = re.compile(r"^(?:name|이름|성명)\s*[:：]\s*(.+)$")
_EMAIL_LABEL = re.compile(r"^(?:e-?mail|이메일|전자\s*우편)\s*[:：]\s*")
_ORG_LABEL = re.compile(r"^(?:affiliation|organization|university|소속|대학교)\s*[:：]\s*")
# Match whole visible fields below. No suffix/prefix address matches are used.
_EMAIL = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+")


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split()).casefold()


def _person(block: ParsedBlock) -> bool:
    if block.tag in _PAGE:
        return False
    attrs = dict(block.attributes)
    classes = set((attrs.get("class") or "").casefold().split())
    itemtypes = (attrs.get("itemtype") or "").split()
    return bool(classes & _CARDS) or any(
        value.rstrip("/") in {"https://schema.org/Person", "http://schema.org/Person"}
        for value in itemtypes
    )


def _chrome(block: ParsedBlock) -> bool:
    attrs = dict(block.attributes)
    roles = set((attrs.get("role") or "").casefold().split())
    markers = set((attrs.get("class") or "").casefold().split())
    markers.add((attrs.get("id") or "").casefold())
    return (block.tag in _CHROME
            or bool(roles & {"contentinfo", "navigation", "complementary", "banner"})
            or bool(markers & {"footer", "site-footer", "navigation", "navbar", "site-header"}))


def _property(block: ParsedBlock, name: str) -> bool:
    return name in (dict(block.attributes).get("itemprop") or "").split()


@dataclass(frozen=True)
class _Unit:
    block_id: int
    value: str
    indices: tuple[int, ...]

    def evidence(self, kind: str) -> IdentityEvidence:
        return IdentityEvidence(kind, self.block_id, self.indices)


class _Document:
    """Index containment once; never join structural siblings into a field."""

    def __init__(self, document: ParsedDocument):
        self.blocks = {block.block_id: block for block in document.blocks}
        self.first_children = {}
        for block in document.blocks:
            self.first_children.setdefault(block.parent_id, block.block_id)
        self.paths = {}
        for block in document.blocks:
            path = []
            current = block
            while current is not None:
                path.append(current.block_id)
                current = self.blocks.get(current.parent_id)
            self.paths[block.block_id] = tuple(path)
        self.units = []
        pending = []
        owner = None

        def flush():
            if pending:
                value = _normalize("".join(document.texts[i].raw_text for i in pending))
                if value:
                    self.units.append(_Unit(owner, value, tuple(pending)))
                pending.clear()

        for index, text in enumerate(document.texts):
            path = self.paths[text.block_id]
            if any(_chrome(self.blocks[bid]) for bid in path):
                flush()
                owner = None
                continue
            flow = next(bid for bid in path if self.blocks[bid].tag not in _INLINE
                        or _property(self.blocks[bid], "name") or _person(self.blocks[bid]))
            if flow != owner:
                flush()
                owner = flow
            pending.append(index)
        flush()
        # A Name dt establishes a separate ownership boundary, including when
        # malformed. Never borrow its dd fields for an enclosing heading.
        self.definition_names = {}
        self.named_lists = set()
        self.ambiguous_lists = set()
        by_block = {}
        for unit in self.units:
            by_block.setdefault(unit.block_id, []).append(unit)
        children = {}
        for block in document.blocks:
            children.setdefault(block.parent_id, []).append(block)
        for bid, block in self.blocks.items():
            if block.tag != "dl":
                continue
            entries = children.get(bid, [])
            for index, entry in enumerate(entries):
                labels = by_block.get(entry.block_id, [])
                if entry.tag != "dt" or len(labels) != 1:
                    continue
                if labels[0].value.rstrip(":：") not in {"name", "이름", "성명"}:
                    continue
                self.named_lists.add(bid)
                descriptions = []
                for following in entries[index + 1:]:
                    if following.tag == "dt":
                        break
                    descriptions.append(following)
                # Several descriptions may be aliases or several people. P0
                # does not infer that relationship, even for repeated values.
                if len(descriptions) != 1:
                    self.ambiguous_lists.add(bid)
                for description in descriptions:
                    values = by_block.get(description.block_id, [])
                    if description.tag != "dd" or len(values) != 1:
                        self.ambiguous_lists.add(bid)
                        continue
                    self.definition_names[description.block_id] = values[0].value

    def inside(self, child: int, root: int) -> bool:
        return root in self.paths[child]

    def local(self, unit: _Unit, root: int) -> bool:
        """No intervening card/container can donate fields to its ancestor."""
        path = self.paths[unit.block_id]
        return root in path and not any(
            self.blocks[bid].tag in _REGIONS or bid in self.named_lists or _person(self.blocks[bid])
            for bid in path[:path.index(root)]
        )

    def roots(self, unit: _Unit) -> tuple[int, ...]:
        roots = []
        for bid in self.paths[unit.block_id]:
            block = self.blocks[bid]
            if block.tag in _REGIONS or bid in self.named_lists or _person(block):
                roots.append(bid)
            if bid in self.named_lists or _person(block) or block.tag in {"tr", "li", "article"}:
                break
        return tuple(roots)


def _name(unit: _Unit, tree: _Document, expected: str) -> str | None:
    block = tree.blocks[unit.block_id]
    labeled = _NAME.fullmatch(unit.value)
    if labeled:
        return labeled[1]
    if unit.block_id in tree.definition_names:
        return tree.definition_names[unit.block_id]
    if block.tag in _HEADINGS or _property(block, "name"):
        return unit.value
    if block.tag == "td":
        parent = tree.blocks.get(block.parent_id)
        if parent and parent.tag == "tr":
            if tree.first_children[parent.block_id] == block.block_id:
                return unit.value
    # Bare names are supported only at a bounded card/item's own text level.
    if unit.value == expected and (_person(block) or block.tag == "li"):
        return unit.value
    return None


def _email(unit: _Unit) -> str | None:
    value = _EMAIL_LABEL.sub("", unit.value)
    return value if _EMAIL.fullmatch(value) else None


def _organization(unit: _Unit) -> str | None:
    value = _ORG_LABEL.sub("", unit.value)
    if re.search(r"\buniversity\b", value) or value.endswith("대학교"):
        return value
    return None


def verify_identity(subject: Subject, document: ParsedDocument) -> IdentityDecision:
    """Compare parsed body fields and return bounded confirmed scope roots.

    Name + exact visible email takes precedence for namesake disambiguation.
    University-only corroboration requires a single matching name region.
    Missing/contradictory fields and unsupported structure are uncertain.
    Rejection requires one explicit profile with BOTH a different name and a
    different explicitly labeled email, and no target name/email elsewhere.
    """
    def decision(status, reason, evidence=(), roots=()):
        return IdentityDecision(document.source_id, status, (reason,),
                                tuple(evidence), tuple(roots))

    uncertain = IdentityStatus.UNCERTAIN
    name = _normalize(subject.name)
    organization = _normalize(subject.organization)
    email = _normalize(str(subject.email))
    if not name:
        return decision(uncertain, "missing_subject_name")
    tree = _Document(document)
    if not tree.units:
        return decision(uncertain, "no_body_text")
    names = [(unit, value) for unit in tree.units
             if (value := _name(unit, tree, name)) is not None]
    matches = [unit for unit, value in names if value == name]
    name_evidence = [unit.evidence("name_match") for unit in matches]

    def safe(root, anchor):
        if root in tree.ambiguous_lists:
            return False
        if not tree.local(anchor, root):
            return False
        if sum(tree.inside(unit.block_id, root) for unit, _ in names) != 1:
            return False
        return not any(
            bid != root and tree.inside(bid, root)
            and (_chrome(block) or _person(block) or block.tag in _REGIONS or bid in tree.named_lists)
            for bid, block in tree.blocks.items()
        )

    verified = []
    ambiguous = False
    conflicting = False
    for anchor in matches:
        for root in tree.roots(anchor):
            if not safe(root, anchor):
                ambiguous = True
                continue
            fields = [unit for unit in tree.units if tree.inside(unit.block_id, root)]
            local = [unit for unit in fields if tree.local(unit, root)]
            # Even a non-local address warns of a potentially mixed region.
            addresses = {match.group() for unit in fields for match in _EMAIL.finditer(unit.value)}
            orgs = {value for unit in local if (value := _organization(unit)) is not None}
            if len(addresses) > 1 or (addresses and email not in addresses) or (orgs and orgs != {organization}):
                conflicting = True
                continue
            email_fields = [unit for unit in local if unit != anchor and email != name
                            and _email(unit) == email]
            org_fields = [unit for unit in local if unit != anchor and organization != name
                          and _organization(unit) == organization]
            if email_fields:
                verified.append((root, "email", (anchor.evidence("name_match"),
                                *(unit.evidence("email_exact_match") for unit in email_fields))))
                break
            if org_fields and organization:
                verified.append((root, "university", (anchor.evidence("name_match"),
                                *(unit.evidence("organization_match") for unit in org_fields))))
                break

    exact = [entry for entry in verified if entry[1] == "email"]
    chosen = exact or (verified if len(matches) == 1 else [])
    if chosen:
        return decision(IdentityStatus.CONFIRMED,
                        "linked_name_email" if exact else "linked_name_university",
                        (item for _, _, evidence in chosen for item in evidence),
                        (root for root, _, _ in chosen))
    if matches:
        reason = ("ambiguous_namesakes" if len(matches) > 1 else
                  "conflicting_identifiers" if conflicting else
                  "ambiguous_region" if ambiguous else "insufficient_evidence")
        return decision(uncertain, reason, name_evidence)

    # Only a single explicitly bounded other-person profile can reject a page.
    profiles = [bid for bid, block in tree.blocks.items() if _person(block)]
    if len(profiles) == 1 and len(names) == 1:
        root = profiles[0]
        anchor, other_name = names[0]
        outside = any(not tree.inside(unit.block_id, root) for unit in tree.units)
        if safe(root, anchor) and other_name != name and not outside:
            other_emails = [unit for unit in tree.units if tree.local(unit, root)
                            and (_EMAIL_LABEL.match(unit.value)
                                 or _property(tree.blocks[unit.block_id], "email"))
                            and _email(unit) is not None]
            addresses = {_email(unit) for unit in other_emails}
            # Rejection requires a name explicitly labeled by the document.
            # Headings and email local parts do not establish a person's name.
            explicit_name = (bool(_NAME.fullmatch(anchor.value))
                             or _property(tree.blocks[anchor.block_id], "name")
                             or anchor.block_id in tree.definition_names)
            target_email_present = any(email in _EMAIL.findall(unit.value) for unit in tree.units)
            if (len(addresses) == 1 and email not in addresses and not target_email_present
                    and explicit_name):
                return decision(IdentityStatus.REJECTED, "explicit_other_profile",
                                (anchor.evidence("name_conflict"),
                                 *(unit.evidence("email_conflict") for unit in other_emails)))
    return decision(uncertain, "no_name_match")
