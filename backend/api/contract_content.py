"""Small allow-list sanitizer for employer-authored contract HTML."""

from html import escape
from html.parser import HTMLParser


ALLOWED_TAGS = {"p", "br", "strong", "b", "em", "i", "u", "ol", "ul", "li",
                "h1", "h2", "h3", "blockquote", "div", "span"}
VOID_TAGS = {"br"}
BLOCKED_WITH_CONTENT = {"script", "style", "iframe", "object", "svg", "math"}
ALIGNMENTS = {"left", "center", "right", "justify"}


class ContractHTMLSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = []
        self.blocked_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in BLOCKED_WITH_CONTENT:
            self.blocked_depth += 1
            return
        if self.blocked_depth or tag not in ALLOWED_TAGS:
            return
        style = ""
        for name, value in attrs:
            if name.lower() != "style":
                continue
            for declaration in value.split(";"):
                key, separator, raw = declaration.partition(":")
                if separator and key.strip().lower() == "text-align" and raw.strip().lower() in ALIGNMENTS:
                    style = f' style="text-align: {raw.strip().lower()}"'
        self.output.append(f"<{tag}{style}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in BLOCKED_WITH_CONTENT:
            self.blocked_depth = max(0, self.blocked_depth - 1)
            return
        if not self.blocked_depth and tag in ALLOWED_TAGS and tag not in VOID_TAGS:
            self.output.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.blocked_depth:
            self.output.append(escape(data))


def sanitize_contract_html(value):
    parser = ContractHTMLSanitizer()
    parser.feed(value or "")
    parser.close()
    return "".join(parser.output).strip()
