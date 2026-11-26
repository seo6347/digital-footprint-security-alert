"""Internal document models shared by Page Explorer and profiling."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedText:
    """Entity-decoded text and its exact slice in ParsedDocument.html_text."""

    block_id: int
    raw_text: str
    normalized_text: str
    start: int
    end: int


@dataclass(frozen=True)
class ParsedBlock:
    """Structural container, never an inferred person or merged evidence quote."""

    block_id: int
    parent_id: int | None
    tag: str
    attributes: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True)
class ParsedLink:
    block_id: int
    href: str
    text: str
    normalized_text: str
    text_indices: tuple[int, ...]
    attributes: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True)
class ParsedMetadata:
    attributes: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True)
class ParsedDocument:
    source_id: str
    original_url: str
    final_url: str
    encoding: str
    html_text: str
    title: str | None
    metadata: tuple[ParsedMetadata, ...]
    blocks: tuple[ParsedBlock, ...]
    texts: tuple[ParsedText, ...]
    links: tuple[ParsedLink, ...]

    @property
    def has_body_text(self) -> bool:
        return any(text.normalized_text for text in self.texts)
