from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import parse_qs, urlparse


@dataclass
class HtmlNode:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["HtmlNode | str"] = field(default_factory=list)


class GhostHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]):
        node = HtmlNode(tag.lower(), {k.lower(): v or "" for k, v in attrs})
        self.stack[-1].children.append(node)
        if node.tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append(node)

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        for idx in range(len(self.stack) - 1, 0, -1):
            if self.stack[idx].tag == tag:
                del self.stack[idx:]
                break

    def handle_data(self, data: str):
        self.stack[-1].children.append(data)


def normalize_youtube_url(src: str) -> str:
    parsed = urlparse(src)
    host = parsed.netloc.lower()
    if host.endswith("youtube.com") and parsed.path.startswith("/embed/"):
        video_id = parsed.path.removeprefix("/embed/").split("/")[0]
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
    if host.endswith("youtube.com") and parsed.path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
    if host.endswith("youtu.be"):
        video_id = parsed.path.strip("/").split("/")[0]
        if video_id:
            return f"https://youtu.be/{video_id}"
    return src


def html_to_markdown(html: Optional[str]) -> str:
    if not html:
        return ""
    parser = GhostHtmlParser()
    parser.feed(html)
    parser.close()
    markdown = render_html_node(parser.root)
    markdown = re.sub(r"[ \t]+\n", "\n", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    markdown = "\n".join(line.strip() for line in markdown.splitlines())
    return markdown.strip()


def render_html_children(node: HtmlNode) -> str:
    return "".join(render_html_node(child) for child in node.children)


def render_html_node(node: HtmlNode | str) -> str:
    if isinstance(node, str):
        return node

    tag = node.tag
    content = render_html_children(node)

    if tag in {"root", "html", "body", "article", "section"}:
        return content
    if tag == "figcaption":
        return f"\n\n{content.strip()}\n\n"
    if tag in {"p", "div", "figure"}:
        return f"{content.strip()}\n\n" if content.strip() else ""
    if tag in {"strong", "b"}:
        return f"**{content.strip()}**"
    if tag in {"em", "i"}:
        return f"*{content.strip()}*"
    if tag == "br":
        return "\n"
    if tag == "hr":
        return "\n---\n\n"
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        level = int(tag[1])
        return f"{'#' * level} {content.strip()}\n\n"
    if tag == "blockquote":
        lines = content.strip().splitlines()
        quoted = "\n".join(f"> {line.strip()}" if line.strip() else ">" for line in lines)
        return f"{quoted}\n\n" if quoted else ""
    if tag == "a":
        href = node.attrs.get("href", "").strip()
        label = content.strip() or href
        return f"[{label}]({href})" if href else label
    if tag in {"iframe", "embed"}:
        src = node.attrs.get("src", "").strip()
        return f"\n{normalize_youtube_url(src)}\n\n" if src else ""
    if tag == "img":
        src = node.attrs.get("src", "").strip()
        alt = node.attrs.get("alt", "").strip().replace("\\", "\\\\").replace("]", "\\]")
        return f"![{alt}]({src})" if src else alt
    if tag in {"ul", "ol"}:
        ordered = tag == "ol"
        items = [child for child in node.children if isinstance(child, HtmlNode) and child.tag == "li"]
        lines = []
        for index, item in enumerate(items, start=1):
            bullet = f"{index}." if ordered else "-"
            lines.append(f"{bullet} {render_html_children(item).strip()}")
        return "\n".join(lines) + ("\n\n" if lines else "")
    if tag == "li":
        return content
    if tag in {"script", "style"}:
        return ""
    return content


