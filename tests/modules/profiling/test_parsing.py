from dataclasses import asdict
from html import unescape
from pathlib import Path

import pytest

from dfsa.modules.profiling import parsing
from dfsa.modules.profiling._types import (
    FetchedHTML, ParseError, ParseFailure, ParsedDocument,
)
from dfsa.modules.profiling.fetch import fetch_html


def fetched(html=b"", charset=None):
    return FetchedHTML("src_001", "https://example.com/old", "https://example.com/lab/index",
                       html, "text/html", charset, 200)


def parse(text, charset=None):
    result = parsing.parse_html(fetched(text.encode("utf-8"), charset))
    assert isinstance(result, ParsedDocument), result
    return result


@pytest.fixture
def people():
    body = (Path(__file__).parent / "fixtures/html/people.html").read_bytes()
    result = parsing.parse_html(fetched(body))
    assert isinstance(result, ParsedDocument)
    return result


def scope_text(document, block_id):
    descendants = {block_id}
    for block in document.blocks:
        if block.parent_id in descendants:
            descendants.add(block.block_id)
    return "".join(text.raw_text for text in document.texts if text.block_id in descendants)


@pytest.mark.parametrize("codec,label", [
    ("utf-8", None), ("utf-8-sig", None), ("euc-kr", "EUC-KR"),
    ("cp949", "cp949"), ("cp949", "ms949"),
])
def test_korean_http_decoding(codec, label):
    result = parsing.parse_html(fetched("<p>홍길동 연구실</p>".encode(codec), label))
    assert isinstance(result, ParsedDocument)
    assert scope_text(result, 0) == "홍길동 연구실"


@pytest.mark.parametrize("declaration", [
    '<meta charset="euc-kr">',
    '<META CHARSET=euc-kr>',
    '<meta http-equiv="Content-Type" content="text/html; charset=EUC-KR">',
])
def test_html_legacy_charset(declaration):
    result = parsing.parse_html(fetched((declaration + "<p>홍길동</p>").encode("euc-kr")))
    assert result.encoding == "euc_kr"
    assert scope_text(result, 0) == "홍길동"


def test_http_charset_takes_precedence():
    result = parse('<meta charset="does-not-exist"><p>한글</p>', "utf-8")
    assert result.encoding == "utf-8" and scope_text(result, 0) == "한글"
    result = parsing.parse_html(fetched(b'<meta charset="utf-8"><p>\xe9</p>', "cp1252"))
    assert result.encoding == "cp1252" and scope_text(result, 0) == "é"


@pytest.mark.parametrize("label,kind", [
    ("", ParseError.INVALID_CHARSET), (" ", ParseError.INVALID_CHARSET),
    ("made-up", ParseError.INVALID_CHARSET), ("windows-949", ParseError.INVALID_CHARSET),
    ("utf-16", ParseError.UNSUPPORTED_CHARSET),
    ("shift_jis", ParseError.UNSUPPORTED_CHARSET), ("base64_codec", ParseError.UNSUPPORTED_CHARSET),
])
@pytest.mark.parametrize("http", [True, False])
def test_invalid_and_unsupported_charsets(label, kind, http):
    body = b"<p>text</p>" if http else f'<meta charset="{label}"><p>text</p>'.encode()
    result = parsing.parse_html(fetched(body, label if http else None))
    assert isinstance(result, ParseFailure) and result.kind == kind
    assert result.error.code == kind.value and not result.error.retryable
    assert result.source_id == result.error.source_id == "src_001"
    assert result.original_url == "https://example.com/old"
    assert result.final_url == "https://example.com/lab/index"


@pytest.mark.parametrize("declaration", ["http", "meta", "http-equiv"])
def test_nul_charset_is_invalid_charset_failure(declaration):
    label = "utf-8\x00"
    if declaration == "meta":
        value = fetched(f'<meta charset="{label}"><p>Alice</p>'.encode())
    elif declaration == "http-equiv":
        value = fetched(f'<meta http-equiv="Content-Type" content="text/html; charset={label}"><p>Alice</p>'.encode())
    else:
        value = fetched(b"<p>Alice</p>", label)
    before = asdict(value)
    result = parsing.parse_html(value)
    assert isinstance(result, ParseFailure)
    assert result.kind == ParseError.INVALID_CHARSET
    assert result.error.code == "invalid_charset" and not result.error.retryable
    assert result.source_id == result.error.source_id == value.source_id
    assert result.original_url == value.original_url and result.final_url == value.final_url
    assert asdict(value) == before


def test_charset_fix_does_not_hide_unrelated_valueerror(monkeypatch):
    def broken(label):
        raise ValueError("codec implementation bug")
    monkeypatch.setattr(parsing.codecs, "lookup", broken)
    with pytest.raises(ValueError, match="codec implementation bug"):
        parsing.parse_html(fetched(b"<p>Alice</p>", "utf-8"))


@pytest.mark.parametrize("body,charset", [
    (b"<p>\xff</p>", None), ("<p>한글</p>".encode("euc-kr"), None),
    (b"<meta charset=utf-8><p>\xff</p>", None),
    (b"<p>\xff</p>", "ascii"), (b"<p>\xb0</p>", "euc-kr"),
    (b"\xff\xfe<\x00p\x00>\x00", None), (b"<p>\x00</p>", "latin-1"),
    ("<p>�</p>".encode(), None),
])
def test_decode_failures_are_not_replaced_or_guessed(body, charset):
    result = parsing.parse_html(fetched(body, charset))
    assert result.kind == ParseError.DECODE_ERROR


@pytest.mark.parametrize("label", ["ascii", "latin-1", "windows-1252", "UTF8", " utf-8 "])
def test_supported_aliases(label):
    assert scope_text(parse("<p>ABC</p>", label), 0) == "ABC"


def test_charset_ignores_comments_script_template():
    document = parse('<!-- <meta charset=bad> --><script>"<meta charset=bad>"</script>'
                     '<template><meta charset=bad></template><p>한글</p>')
    assert document.encoding == "utf-8"


def test_title_metadata_and_source_context(people):
    assert people.title == "Members & Research"
    metas = [dict(meta.attributes) for meta in people.metadata]
    assert {"name": "description", "content": "Faculty & students"} in metas
    assert {"property": "og:title", "content": "Our lab"} in metas
    assert "Members & Research" not in scope_text(people, 0)
    assert people.source_id == "src_001" and people.final_url.endswith("/lab/index")


def test_card_scopes_do_not_merge_people(people):
    cards = [b for b in people.blocks if dict(b.attributes).get("class") == "profile-card"]
    assert len(cards) == 2 and cards[0].parent_id == cards[1].parent_id
    a, b = (scope_text(people, card.block_id) for card in cards)
    assert "Professor A" in a and "a@example.com" in a and "b@example.com" not in a
    assert "Professor B" in b and "b@example.com" in b and "a@example.com" not in b
    assert not any("Professor A" in t.raw_text and "Professor B" in t.raw_text for t in people.texts)


def test_headings_nested_inline_list_table(people):
    assert any(b.tag == "h1" and scope_text(people, b.block_id) == "Research Team" for b in people.blocks)
    interests = [b for b in people.blocks if b.tag == "p" and "Research Interests" in scope_text(people, b.block_id)]
    assert scope_text(people, interests[0].block_id) == "Research Interests: Artificial Intelligence"
    items = [b for b in people.blocks if b.tag == "li"]
    assert [scope_text(people, b.block_id) for b in items] == ["Student A AI", "Student B"]
    rows = [b for b in people.blocks if b.tag == "tr"]
    assert len(rows) == 3 and rows[1].parent_id == rows[2].parent_id
    assert "c@example.com" in scope_text(people, rows[1].block_id)
    assert "d@example.com" not in scope_text(people, rows[1].block_id)
    cells = [b for b in people.blocks if b.parent_id == rows[1].block_id]
    assert [scope_text(people, b.block_id) for b in cells] == ["Member C", "c@example.com"]


def test_raw_normalized_and_original_offsets(people):
    assert any(t.raw_text == "  Original CASE\n  " and t.normalized_text == "original case" for t in people.texts)
    assert any(t.raw_text == "한" for t in people.texts)
    assert any(t.raw_text == "\xa0" for t in people.texts)
    for text in people.texts:
        assert text.raw_text == unescape(people.html_text[text.start:text.end])
        assert text.normalized_text == " ".join(text.raw_text.split()).casefold()
        assert 0 <= text.block_id < len(people.blocks)
    assert [t.start for t in people.texts] == sorted(t.start for t in people.texts)
    assert "&#54620;" in people.html_text


def test_excluded_elements(people):
    body = scope_text(people, 0)
    for word in ("script", "style", "comment", "template", "decoration", "hidden", "aria"):
        assert f"{word}@example.com" not in body


@pytest.mark.parametrize("element", ["template", "div hidden", 'span aria-hidden="true"'])
def test_excluded_malformed_subtree_cannot_close_visible_ancestor(element):
    tag = element.split()[0]
    document = parse(f"<section><{element}></section><p>secret</p></{tag}><p>public</p></section>")
    assert scope_text(document, 0) == "public"


def test_hidden_title_and_metadata_do_not_leak():
    document = parse('<div hidden><title>Secret</title><meta name=description content=secret></div>'
                     '<head><title>Public</title></head><p>visible</p>')
    assert document.title == "Public" and not document.metadata
    assert scope_text(document, 0) == "visible"


def test_cp949_extended_korean_requires_correct_declaration():
    body = "<p>똠</p>".encode("cp949")
    assert scope_text(parsing.parse_html(fetched(body, "cp949")), 0) == "똠"
    assert parsing.parse_html(fetched(body, "euc-kr")).kind == ParseError.DECODE_ERROR


def test_nested_lists_preserve_outer_and_inner_boundaries():
    document = parse("<ul><li>A<ul><li>inner one<li>inner two</ul><li>B</ul>")
    items = [b for b in document.blocks if b.tag == "li"]
    assert len(items) == 4
    assert items[0].parent_id == items[3].parent_id
    assert items[1].parent_id == items[2].parent_id != items[0].parent_id
    assert scope_text(document, items[3].block_id) == "B"


def test_links_preserve_text_attributes_and_scope(people):
    link = next(link for link in people.links if link.href.startswith("../"))
    assert link.href == "../people/a?q=1&x=2" and link.text == " Profile A "
    assert link.normalized_text == "profile a"
    assert dict(link.attributes)["href"] == link.href
    assert "Professor A" in scope_text(people, link.block_id)
    assert link.text == "".join(people.texts[i].raw_text for i in link.text_indices)


@pytest.mark.parametrize("href", ["/relative", "http://127.0.0.1/", "javascript:alert(1)",
                                   "file:///secret", "https://[", "//other.example/x"])
def test_links_are_untrusted_data_never_fetched(href):
    document = parse(f'<base href="https://ignored.example/"><p><a href="{href}">Open</a></p>')
    assert document.links[0].href == href


@pytest.mark.parametrize("html,title,has_text", [
    ("", None, False), (" \n ", None, False), ("<html><body></body></html>", None, False),
    ("<head><title>Only &amp; Title</title></head>", "Only & Title", False),
    ("<head><meta name=description content=text></head>", None, False),
    ("<script>ignored</script>", None, False), ("<p>Hello", None, True),
    ("Plain HTML fragment", None, True),
])
def test_empty_title_only_and_fragments(html, title, has_text):
    document = parse(html)
    assert document.title == title and document.has_body_text == has_text


@pytest.mark.parametrize("head_end", ["</head>", ""])
@pytest.mark.parametrize("body_start,body_end", [("<body>", "</body>"), ("", "")])
def test_head_end_omission_preserves_metadata_people_and_provenance(head_end, body_start, body_end):
    head = ('<html><head><meta charset=utf-8><title>Lab &amp; Members</title>'
            '<meta name=description content="Team &amp; research">')
    body = ('<div class=card><h2>Professor A</h2><p>Email: '
            '<a href="mailto:a@example.com">a@example.com</a> &amp; AI</p></div>'
            '<div class=card><h2>Professor B</h2><p>b@example.com</p></div>')
    document = parse(head + head_end + body_start + body + body_end + "</html>")
    reference = parse(head + "</head>" + body_start + body + body_end + "</html>")
    assert document.has_body_text and document.title == "Lab & Members"
    assert document.title == reference.title and document.metadata == reference.metadata
    assert document.blocks == reference.blocks
    assert document.links == reference.links
    assert [(t.block_id, t.raw_text, t.normalized_text) for t in document.texts] == [
        (t.block_id, t.raw_text, t.normalized_text) for t in reference.texts
    ]
    cards = [b for b in document.blocks if dict(b.attributes).get("class") == "card"]
    assert len(cards) == 2 and cards[0].parent_id == cards[1].parent_id
    assert "a@example.com" in scope_text(document, cards[0].block_id)
    assert "b@example.com" not in scope_text(document, cards[0].block_id)
    assert "b@example.com" in scope_text(document, cards[1].block_id)
    assert "a@example.com" not in scope_text(document, cards[1].block_id)
    for text in document.texts:
        assert text.raw_text == unescape(document.html_text[text.start:text.end])


@pytest.mark.parametrize("body", ["Alice", "&#65;lice", "&nbsp;Alice"])
def test_plain_body_text_implicitly_ends_head(body):
    document = parse("<head><title>Lab</title>" + body + "<p>Profile</p>")
    reference = parse("<head><title>Lab</title></head>" + body + "<p>Profile</p>")
    assert document.title == reference.title == "Lab"
    assert [(t.block_id, t.raw_text, t.normalized_text) for t in document.texts] == [
        (t.block_id, t.raw_text, t.normalized_text) for t in reference.texts
    ]
    for text in document.texts:
        assert text.raw_text == unescape(document.html_text[text.start:text.end])


def test_head_whitespace_comments_and_inert_content_do_not_end_head():
    document = parse('<head> \n<!-- comment --><title>Lab &amp; Team</title>'
                     '<script>"<body>script"</script><style>body { color: red; }</style>'
                     '<template><body><p>secret</p></body></template>'
                     '<meta name=description content=retained><body><p>Visible</p></body>')
    assert document.title == "Lab & Team"
    assert {"name": "description", "content": "retained"} in [dict(m.attributes) for m in document.metadata]
    assert scope_text(document, 0) == "Visible"


def test_head_only_without_end_tag_remains_empty():
    document = parse('<head><title>Lab</title> \n<!-- empty body -->')
    assert document.title == "Lab" and not document.has_body_text


@pytest.mark.parametrize("html,tag,expected", [
    ("<ul><li>A<li>B</ul>", "li", ["A", "B"]),
    ("<table><tr><td>A<td>a<tr><td>B<td>b</table>", "tr", ["Aa", "Bb"]),
    ("<p>A<p>B", "p", ["A", "B"]),
    ("<dl><dt>A<dd>a<dt>B<dd>b</dl>", "dt", ["A", "B"]),
])
def test_simple_omitted_end_tags(html, tag, expected):
    document = parse(html)
    blocks = [b for b in document.blocks if b.tag == tag]
    assert [scope_text(document, b.block_id) for b in blocks] == expected
    assert len({b.parent_id for b in blocks}) == 1


def test_mismatched_inline_end_keeps_sibling_cards_separate():
    document = parse('<div class=card><p>A<b>email</div><div class=card>B</div>')
    cards = [b for b in document.blocks if b.tag == "div"]
    assert [scope_text(document, b.block_id) for b in cards] == ["Aemail", "B"]


def test_inline_card_attributes_preserve_boundaries():
    document = parse('<span class=card>A</span><span class=card>B</span>')
    cards = [b for b in document.blocks if b.tag == "span"]
    assert [scope_text(document, b.block_id) for b in cards] == ["A", "B"]


def test_entities_are_decoded_once_and_have_exact_provenance():
    document = parse("<p>A&amp;lt;B &#x41; &unknown; &amp missing</p>")
    assert scope_text(document, 0) == "A&lt;B A &unknown; & missing"
    for text in document.texts:
        assert unescape(document.html_text[text.start:text.end]) == text.raw_text


def test_line_break_is_structural_and_does_not_invent_evidence():
    document = parse("<p>A<br>B</p><p>C</p>")
    assert any(b.tag == "br" for b in document.blocks)
    assert [t.raw_text for t in document.texts] == ["A", "B", "C"]
    assert not any("AB" == t.raw_text or "BC" == t.raw_text for t in document.texts)


@pytest.mark.parametrize("html,kind", [
    ("<![broken]><p>A</p>", ParseError.INVALID_DOCUMENT),
    ("<div>" * 257 + "A", ParseError.STRUCTURE_LIMIT),
])
def test_uninterpretable_structure_is_failure(html, kind):
    result = parsing.parse_html(fetched(html.encode()))
    assert isinstance(result, ParseFailure) and result.kind == kind


def test_input_immutability_and_determinism(people):
    value = fetched(people.html_text.encode())
    before = asdict(value)
    first = parsing.parse_html(value)
    assert asdict(value) == before
    assert first == parsing.parse_html(value)


def test_fetch_result_is_direct_parse_input(source, public_dns, response_factory, opener_factory):
    response = response_factory("<p>한글</p>".encode(), headers={"Content-Type": "text/html; charset=utf-8"})
    value = fetch_html(source, resolver=public_dns, opener=opener_factory(response))
    document = parsing.parse_html(value)
    assert isinstance(document, ParsedDocument) and scope_text(document, 0) == "한글"
    assert document.source_id == source.source_id and document.original_url == source.url


def test_fetch_nul_http_charset_becomes_parse_failure(source, public_dns, response_factory, opener_factory):
    response = response_factory(b"<p>Alice</p>", headers={"Content-Type": 'text/html; charset="utf-8\x00"'})
    value = fetch_html(source, resolver=public_dns, opener=opener_factory(response))
    assert isinstance(value, FetchedHTML) and value.charset == "utf-8\x00"
    result = parsing.parse_html(value)
    assert isinstance(result, ParseFailure) and result.kind == ParseError.INVALID_CHARSET


def test_programming_errors_propagate(monkeypatch):
    def broken(self, data):
        raise RuntimeError("bug")
    monkeypatch.setattr(parsing._DocumentParser, "feed", broken)
    with pytest.raises(RuntimeError, match="bug"):
        parsing.parse_html(fetched(b"<p>hello</p>"))
