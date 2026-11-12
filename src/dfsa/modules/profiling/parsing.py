"""Static Phase 2 parsing, without identity/exposure decisions or network access.

Text runs preserve case/whitespace after HTML entity decoding, with offsets into
the retained decoded HTML. Blocks preserve containment, not person ownership.
Never join all document runs into an evidence quote: select a structural scope
and check its original HTML in later phases. Inline text runs remain ordered.

HTTP charset > first HTML meta charset > UTF-8 BOM/default. A declared codec is
decoded strictly; failed declarations do not trigger guesses. Undeclared legacy
bytes fail: EUC-KR/CP949 require a declaration. Supported codecs are UTF-8, ASCII,
EUC-KR, CP949, Latin-1 and Windows-1252 (including Python codec aliases).

HTMLParser is not a browser DOM or CSS engine. Simple omitted list/row/cell/p
ends and head ends before body content are repaired; arbitrary malformed nesting,
CSS visibility, JS, XML charset
declarations and HTML base URLs are not interpreted. Raw hrefs are untrusted
references, never approved URLs; later fetching must use Phase 1 URL policy.
"""

import codecs
import re
from html import unescape
from html.parser import HTMLParser

from dfsa.contracts.common import ErrorDetail

from ._types import (
    FetchedHTML, ParseError, ParseFailure, ParsedBlock, ParsedDocument,
    ParsedLink, ParsedMetadata, ParsedText,
)

_CODECS = {"utf-8", "utf-8-sig", "ascii", "euc_kr", "cp949", "iso8859-1", "cp1252"}
_VOID = set("area base br col embed hr img input link meta param source track wbr".split())
_SKIP = {"script", "style", "template", "svg", "canvas"}
_BLOCK = set((
    "html body address article aside blockquote div dl dt dd fieldset figcaption "
    "figure footer form h1 h2 h3 h4 h5 h6 header hr li main nav ol p pre section "
    "table caption colgroup thead tbody tfoot tr td th ul details summary br"
).split())
_P_END = _BLOCK - {"html", "body", "br"}
_HEAD_CONTENT = {"base", "basefont", "bgsound", "link", "meta", "title",
                 "noscript", "noframes", "script", "style", "template"}


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


class _Problem(Exception):
    def __init__(self, kind: ParseError, message: str):
        super().__init__(message)
        self.kind = kind


class _CharsetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.charset = None
        self.inert = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.inert.append(tag)
        if self.inert or tag != "meta" or self.charset is not None:
            return
        values = dict(attrs)
        if "charset" in values:
            self.charset = values["charset"] or ""
        elif (values.get("http-equiv") or "").lower() == "content-type":
            match = re.search(r"charset\s*=\s*[\"']?([^\s;\"']*)", values.get("content") or "", re.I)
            if match:
                self.charset = match[1]

    def handle_endtag(self, tag):
        if self.inert and tag == self.inert[-1]:
            self.inert.pop()


def _decode(fetched: FetchedHTML) -> tuple[str, str]:
    label = fetched.charset
    if label is None:
        sniff = _CharsetParser()
        # Latin-1 is a reversible byte view only, not an encoding guess.
        try:
            sniff.feed(fetched.html.decode("latin-1"))
            sniff.close()
        except (ValueError, AssertionError) as exc:
            raise _Problem(ParseError.INVALID_DOCUMENT, "Malformed HTML declaration") from exc
        label = sniff.charset
    if label is None:
        label = "utf-8"
    # codecs.lookup raises ValueError for embedded NUL. Reject that external
    # input explicitly rather than catching unrelated ValueErrors in parsing.
    if "\x00" in label:
        raise _Problem(ParseError.INVALID_CHARSET, "Charset declaration contains NUL")
    try:
        encoding = codecs.lookup(label.strip()).name
    except LookupError as exc:
        raise _Problem(ParseError.INVALID_CHARSET, "Unknown or empty charset declaration") from exc
    if encoding not in _CODECS:
        raise _Problem(ParseError.UNSUPPORTED_CHARSET, "Unsupported charset declaration")
    try:
        text = fetched.html.decode(encoding, errors="strict")
    except UnicodeDecodeError as exc:
        raise _Problem(ParseError.DECODE_ERROR, "HTML bytes do not match the selected charset") from exc
    if text.startswith("\ufeff") and encoding in {"utf-8", "utf-8-sig"}:
        text = text[1:]
    if "\x00" in text or "\ufffd" in text:
        raise _Problem(ParseError.DECODE_ERROR, "HTML contains NUL or replacement characters")
    return text, encoding


class _DocumentParser(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.line_starts = [0] + [m.end() for m in re.finditer("\n", html)]
        self.blocks = [ParsedBlock(0, None, "document", ())]
        self.texts = []
        self.metadata = []
        self.links = []
        # Frames: tag, inherited block id, excluded, title, link draft.
        self.stack = []
        self.titles = []

    def _close(self, index):
        del self.stack[index:]

    def _implicit_end(self, tag):
        # Only close an exposed head frame. Tags within title/inert subtrees
        # must not be interpreted as the start of body content.
        if self.stack and self.stack[-1][0] == "head" and tag not in _HEAD_CONTENT:
            self._close(-1)
        # Close only within the relevant container, preserving nested lists/tables.
        rules = {
            "li": ({"li"}, {"ul", "ol"}),
            "dt": ({"dt", "dd"}, {"dl"}), "dd": ({"dt", "dd"}, {"dl"}),
            "tr": ({"tr"}, {"table", "thead", "tbody", "tfoot"}),
            "td": ({"td", "th"}, {"tr", "table"}),
            "th": ({"td", "th"}, {"tr", "table"}),
        }
        targets, barriers = rules.get(tag, (set(), set()))
        for i in range(len(self.stack) - 1, -1, -1):
            current = self.stack[i][0]
            if current in targets or (tag in _P_END and current == "p"):
                self._close(i)
                break
            if current in barriers:
                break

    def handle_starttag(self, tag, attrs):
        if len(self.stack) >= 256 or len(self.blocks) >= 100_000:
            raise _Problem(ParseError.STRUCTURE_LIMIT, "HTML structure exceeds parser limits")
        parent = self.stack[-1] if self.stack else None
        excluded = bool(parent and parent[2])
        if not excluded:
            self._implicit_end(tag)
        parent = self.stack[-1] if self.stack else None
        values = dict(attrs)
        excluded = excluded or tag in _SKIP or "hidden" in values or (values.get("aria-hidden") or "").lower() == "true"
        in_title = tag == "title" or bool(parent and parent[3])
        if tag == "title" and not excluded:
            self.titles.append([])
        if tag == "meta" and not excluded:
            self.metadata.append(ParsedMetadata(tuple(attrs)))
        block = parent[1] if parent else 0
        if (tag in _BLOCK or any(key in values for key in ("id", "class", "role", "itemscope", "itemprop"))) and not excluded:
            block = len(self.blocks)
            self.blocks.append(ParsedBlock(block, parent[1] if parent else 0, tag, tuple(attrs)))
        link = None
        if tag == "a" and not excluded and values.get("href") is not None:
            link = [block, values["href"], [], tuple(attrs)]
            self.links.append(link)
        if tag not in _VOID:
            self.stack.append((tag, block, excluded, in_title, link))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            # An end tag inside an inert/hidden subtree cannot close its visible
            # ancestor and accidentally expose the remaining excluded content.
            if self.stack[-1][2] and not self.stack[i][2]:
                return
            if self.stack[i][0] == tag:
                self._close(i)
                return

    def _text(self, source: str, *, reference: bool = False):
        raw = unescape(source) if reference else source
        if self.stack and self.stack[-1][2]:
            return
        if self.stack and self.stack[-1][3]:
            self.titles[-1].append(raw)
            return
        if self.stack and self.stack[-1][0] == "head" and raw.strip(" \t\r\n\f"):
            self._close(-1)
        if any(frame[0] == "head" for frame in self.stack):
            return
        line, column = self.getpos()
        start = self.line_starts[line - 1] + column
        block = self.stack[-1][1] if self.stack else 0
        index = len(self.texts)
        self.texts.append(ParsedText(block, raw, _normalize(raw), start, start + len(source)))
        for frame in self.stack:
            if frame[4] is not None:
                frame[4][2].append(index)

    def handle_data(self, data):
        # HTMLParser already leaves literal text unchanged; do not unescape twice.
        self._text(data)

    def handle_entityref(self, name):
        self._reference("&" + name)

    def handle_charref(self, name):
        self._reference("&#" + name)

    def _reference(self, prefix):
        line, column = self.getpos()
        start = self.line_starts[line - 1] + column
        source = prefix + (";" if self.html.startswith(";", start + len(prefix)) else "")
        self._text(source, reference=True)

    def unknown_decl(self, data):
        raise _Problem(ParseError.INVALID_DOCUMENT, "Unsupported HTML declaration")


def parse_html(fetched: FetchedHTML) -> ParsedDocument | ParseFailure:
    """Parse one fetched source. Expected input failures are per-source results.

    Empty/title-only documents succeed. Programming errors propagate. Metadata
    attributes and hrefs are entity decoded; original spellings remain in HTML.
    No public processing/identity/module status is assigned here.
    """
    try:
        html, encoding = _decode(fetched)
        parser = _DocumentParser(html)
        try:
            parser.feed(html)
            parser.close()
        except (ValueError, AssertionError) as exc:
            raise _Problem(ParseError.INVALID_DOCUMENT, "Malformed HTML declaration") from exc
        links = []
        for block, href, indices, attrs in parser.links:
            text = "".join(parser.texts[i].raw_text for i in indices)
            links.append(ParsedLink(block, href, text, _normalize(text), tuple(indices), attrs))
        return ParsedDocument(
            fetched.source_id, fetched.original_url, fetched.final_url, encoding,
            html, "".join(parser.titles[0]) if parser.titles else None,
            tuple(parser.metadata), tuple(parser.blocks), tuple(parser.texts), tuple(links),
        )
    except _Problem as exc:
        return ParseFailure(
            fetched.source_id, fetched.original_url, fetched.final_url, exc.kind,
            ErrorDetail(code=exc.kind.value, message=str(exc), retryable=False,
                        source_id=fetched.source_id),
        )
