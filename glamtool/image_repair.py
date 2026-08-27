from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from typing import Callable, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx


WORDPRESS_SIZE_RE = re.compile(
    r"-(?P<width>\d+)x(?P<height>\d+)(?=\.(?:avif|gif|jpe?g|png|webp)$)",
    re.IGNORECASE,
)


class ImageRepairError(ValueError):
    """Raised when embedded image HTML cannot be inspected safely."""


@dataclass(frozen=True)
class SrcsetCandidate:
    url: str
    descriptor: str = ""


@dataclass(frozen=True)
class ImageRepairResult:
    html: str
    checked: int
    repaired: int
    skipped: int
    broken: int


@dataclass(frozen=True)
class _ImageTag:
    start: int
    end: int
    attrs: list[tuple[str, Optional[str]]]
    self_closing: bool


class _ImageTagParser(HTMLParser):
    """Locate img start tags while leaving all other source HTML byte-for-byte intact."""

    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.cursor = 0
        self.tags: list[_ImageTag] = []

    def _record(self, tag: str, attrs: list[tuple[str, Optional[str]]], self_closing: bool):
        if tag.lower() != "img":
            return
        raw = self.get_starttag_text()
        if raw is None:
            raise ImageRepairError("Could not read an img start tag")
        start = self.source.find(raw, self.cursor)
        if start < 0:
            raise ImageRepairError("Could not locate a parsed img tag in the source HTML")
        end = start + len(raw)
        self.tags.append(_ImageTag(start, end, attrs, self_closing))
        self.cursor = end

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]):
        self._record(tag, attrs, False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]):
        self._record(tag, attrs, True)


def wordpress_original_url(url: str) -> Optional[str]:
    """Remove a final WordPress -WIDTHxHEIGHT suffix without changing query or fragment."""
    parsed = urlsplit(url)
    repaired_path, count = WORDPRESS_SIZE_RE.subn("", parsed.path, count=1)
    if count == 0:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, repaired_path, parsed.query, parsed.fragment))


def parse_srcset(value: str) -> list[SrcsetCandidate]:
    """Parse ordinary srcset candidates while retaining commas inside URL query strings."""
    candidates: list[SrcsetCandidate] = []
    index = 0
    length = len(value)

    while index < length:
        while index < length and (value[index].isspace() or value[index] == ","):
            index += 1
        if index >= length:
            break

        url_start = index
        while index < length and not value[index].isspace():
            index += 1
        url = value[url_start:index]

        # A candidate without a descriptor may end with its separator comma.
        trailing_separator = url.endswith(",")
        if trailing_separator:
            url = url.rstrip(",")

        while index < length and value[index].isspace():
            index += 1
        descriptor = ""
        if not trailing_separator:
            descriptor_start = index
            while index < length and value[index] != ",":
                index += 1
            descriptor = value[descriptor_start:index].strip()

        if index < length and value[index] == ",":
            index += 1
        if url:
            candidates.append(SrcsetCandidate(url, descriptor))

    return candidates


def render_srcset(candidates: list[SrcsetCandidate]) -> str:
    return ", ".join(
        f"{candidate.url} {candidate.descriptor}".rstrip() for candidate in candidates
    )


def image_url_loads(client: httpx.Client, url: str) -> bool:
    """Check a browser-loadable URL, retrying with GET for servers that reject HEAD."""
    head = client.head(url)
    if head.is_success:
        return True
    response = client.get(url, headers={"Range": "bytes=0-0"})
    return response.is_success


def _render_img(attrs: list[tuple[str, Optional[str]]], self_closing: bool) -> str:
    rendered: list[str] = []
    for name, value in attrs:
        if value is None:
            rendered.append(name)
        else:
            rendered.append(f'{name}="{escape(value, quote=True)}"')
    suffix = " />" if self_closing else ">"
    return f"<img{' ' if rendered else ''}{' '.join(rendered)}{suffix}"


def _attribute_index(attrs: list[tuple[str, Optional[str]]], name: str) -> Optional[int]:
    for index, (attribute_name, _) in enumerate(attrs):
        if attribute_name.lower() == name:
            return index
    return None


def _set_attribute(attrs: list[tuple[str, Optional[str]]], name: str, value: str):
    index = _attribute_index(attrs, name)
    if index is None:
        attrs.append((name, value))
    else:
        attrs[index] = (attrs[index][0], value)


def _remove_attribute(attrs: list[tuple[str, Optional[str]]], name: str):
    attrs[:] = [(key, value) for key, value in attrs if key.lower() != name]


def repair_embedded_images(
    html: str,
    *,
    post_url: str,
    check_url: Callable[[str], bool],
) -> ImageRepairResult:
    """Repair broken img src/srcset values and preserve all non-img source markup."""
    parser = _ImageTagParser(html)
    try:
        parser.feed(html)
        parser.close()
    except ImageRepairError:
        raise
    except Exception as exc:
        raise ImageRepairError(f"Could not parse post HTML: {exc}") from exc

    cache: dict[str, bool] = {}

    def loads(raw_url: str) -> bool:
        value = raw_url.strip()
        if not value:
            return False
        if value.startswith("data:"):
            return True
        absolute_url = urljoin(post_url, value)
        parsed = urlsplit(absolute_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        request_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
        if request_url not in cache:
            cache[request_url] = check_url(request_url)
        return cache[request_url]

    replacements: list[tuple[int, int, str]] = []
    repaired_count = 0
    broken_count = 0

    for tag in parser.tags:
        attrs = list(tag.attrs)
        original_attrs = list(attrs)
        src_index = _attribute_index(attrs, "src")
        src = attrs[src_index][1] if src_index is not None else None
        src = src or ""
        working_src = src if loads(src) else ""

        if not working_src and src:
            original = wordpress_original_url(src)
            if original and loads(original):
                working_src = original

        valid_candidates: list[SrcsetCandidate] = []
        srcset_index = _attribute_index(attrs, "srcset")
        srcset_value = attrs[srcset_index][1] if srcset_index is not None else None
        srcset_candidates = parse_srcset(srcset_value or "")
        for candidate in srcset_candidates:
            if loads(candidate.url):
                valid_candidates.append(candidate)

        if not working_src and valid_candidates:
            working_src = valid_candidates[0].url

        if working_src and working_src != src:
            _set_attribute(attrs, "src", working_src)

        if srcset_index is not None and len(valid_candidates) != len(srcset_candidates):
            if valid_candidates:
                _set_attribute(attrs, "srcset", render_srcset(valid_candidates))
            else:
                _remove_attribute(attrs, "srcset")
                _remove_attribute(attrs, "sizes")

        changed = attrs != original_attrs
        if not working_src:
            broken_count += 1
        elif changed:
            repaired_count += 1
            replacements.append((tag.start, tag.end, _render_img(attrs, tag.self_closing)))

    repaired_html = html
    for start, end, replacement in reversed(replacements):
        repaired_html = repaired_html[:start] + replacement + repaired_html[end:]

    checked = len(parser.tags)
    return ImageRepairResult(
        html=repaired_html,
        checked=checked,
        repaired=repaired_count,
        skipped=checked - repaired_count - broken_count,
        broken=broken_count,
    )
