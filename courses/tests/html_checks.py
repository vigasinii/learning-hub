from html.parser import HTMLParser

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class MarkupInspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.errors = []
        self.label_targets = set()
        self.control_ids = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "label" and attributes.get("for"):
            self.label_targets.add(attributes["for"])
        if tag in ("input", "select", "textarea") and attributes.get("type") not in ("hidden", "submit"):
            self.control_ids.append(attributes.get("id"))
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> with open tags {self.stack[-3:]}")
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
            return
        self.stack.pop()


def inspect_markup(html):
    inspector = MarkupInspector()
    inspector.feed(html)
    inspector.close()
    problems = list(inspector.errors)
    if inspector.stack:
        problems.append(f"unclosed tags: {inspector.stack}")
    unlabeled = [control for control in inspector.control_ids if control not in inspector.label_targets]
    if unlabeled:
        problems.append(f"controls without a label: {unlabeled}")
    return problems
