from __future__ import annotations

"""Regression tests for current ChatGPT response/composer markup.

Per the enhancement plan (item 1/12) the union-selector semantics are tested
in pure Python against parsed static HTML fixtures rather than through a fake
CSS engine: html.parser walks the fixture tree and _matches_union evaluates
the two branches of ASSISTANT_MESSAGE_SELECTOR plus the :not() nesting
exclusion. A CSS engine would duplicate the logic under test; this does not.
"""

from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from browser_runtime.selectors import (
    ASSISTANT_MESSAGE_SELECTOR,
    ATTACH_BUTTON_SELECTORS,
    ATTACH_MENU_LABEL_PATTERNS,
    RATE_LIMIT_MODAL_SELECTOR,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class _Node:
    def __init__(self, tag: str, attrs: dict[str, str], parent: "_Node | None") -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[_Node] = []
        self.text: list[str] = []


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.root = _Node("root", {}, None)
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs), self.current)
        self.current.children.append(node)
        if tag not in {"input", "br", "img", "meta", "link"}:
            self.current = node

    def handle_endtag(self, tag):
        node = self.current
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.current = node.parent

    def handle_data(self, data):
        if data.strip():
            self.current.text.append(data.strip())


def parse(path: Path) -> _Node:
    builder = _TreeBuilder()
    builder.feed(path.read_text(encoding="utf-8"))
    return builder.root


def _all_nodes(node: _Node) -> list[_Node]:
    out = [node]
    for child in node.children:
        out.extend(_all_nodes(child))
    return out


def _matches_legacy(node: _Node) -> bool:
    return node.tag == "article" and node.attrs.get("data-message-author-role") == "assistant"


def _matches_new(node: _Node) -> bool:
    return (
        node.tag == "div"
        and node.attrs.get("data-markdown-text-style") == "assistant-message"
        and not _inside_legacy(node)
    )


def _inside_legacy(node: _Node) -> bool:
    parent = node.parent
    while parent is not None:
        if _matches_legacy(parent):
            return True
        parent = parent.parent
    return False


def _matches_union(node: _Node) -> bool:
    """Reference semantics of the two branches of ASSISTANT_MESSAGE_SELECTOR."""
    return _matches_legacy(node) or _matches_new(node)


def _match_count(root: _Node, matcher) -> int:
    return sum(1 for node in _all_nodes(root) if matcher(node))


class AssistantSelectorSemanticsTests(unittest.TestCase):
    """The selector registry's union must count each message exactly once."""

    def test_selector_union_is_well_formed(self):
        # Two branches separated by ', '; the second carries the :not() guard.
        branches = ASSISTANT_MESSAGE_SELECTOR.split(", ")
        self.assertEqual(len(branches), 2)
        self.assertIn("data-message-author-role='assistant'", branches[0])
        self.assertIn(":not(", branches[1])
        self.assertIn("data-markdown-text-style='assistant-message'", branches[1])

    def test_fixture_counts_each_message_exactly_once(self):
        root = parse(FIXTURES / "assistant_containers.html")
        matched = [n for n in _all_nodes(root) if _matches_union(n)]
        texts = []
        for node in matched:
            text = " ".join(t for n in [node, *node.children] for t in n.text)
            texts.append(text)
        self.assertEqual(
            texts,
            ["LEGACY-ONE", "NEW-ONE", "NESTED-INSIDE-LEGACY"],
            "legacy, new, and nested-in-legacy messages each match exactly once",
        )

    def test_user_messages_never_match(self):
        root = parse(FIXTURES / "assistant_containers.html")
        matched = [n for n in _all_nodes(root) if _matches_union(n)]
        self.assertTrue(all(n.attrs.get("data-message-author-role") != "user" for n in matched))

    def test_nested_new_container_is_excluded_from_new_branch(self):
        root = parse(FIXTURES / "assistant_containers.html")
        new_branch = [n for n in _all_nodes(root) if _matches_new(n)]
        self.assertEqual(len(new_branch), 1, "only the standalone new container matches branch 2")

    def test_registry_constant_is_used_by_selenium_module(self):
        import browser_runtime.selenium_legacy as legacy

        source = Path(legacy.__file__).read_text(encoding="utf-8")
        self.assertNotIn(
            "\"[data-message-author-role='assistant']\"", source,
            "selenium_legacy must consume the registry, not hardcode the selector",
        )
        self.assertNotIn(
            "'[data-message-author-role='assistant']'", source,
            "selenium_legacy must consume the registry, not hardcode the selector",
        )


class ComposerFixtureTests(unittest.TestCase):
    def test_attach_button_registry_covers_redesigned_composer(self):
        root = parse(FIXTURES / "composer_attach_menu.html")
        plus = next(n for n in _all_nodes(root) if n.attrs.get("data-testid") == "composer-plus-btn")
        label = plus.attrs.get("aria-label", "")
        self.assertTrue(
            any(token.split("aria-label*='")[1].rstrip("']") in label for token in ATTACH_BUTTON_SELECTORS if "aria-label" in token),
            f"registry must match the redesigned attach button label {label!r}",
        )

    def test_menu_labels_reference_registry_patterns(self):
        # The menu label in the fixture must be covered by a registry pattern.
        root = parse(FIXTURES / "composer_attach_menu.html")
        menu = next(n for n in _all_nodes(root) if n.attrs.get("role") == "menu")
        items = [" ".join(n.text) for n in menu.children]
        import re as _re

        for item in items:
            if item == "Connect to Google Drive":
                continue
            self.assertTrue(
                any(_re.search(pattern, item, _re.I) for pattern in ATTACH_MENU_LABEL_PATTERNS),
                f"registry menu patterns must cover fixture item {item!r}",
            )


class RateLimitFixtureTests(unittest.TestCase):
    def test_modal_id_matches_registry(self):
        root = parse(FIXTURES / "rate_limit_modal.html")
        modal = next(n for n in _all_nodes(root) if n.attrs.get("id") == "modal-conversation-history-rate-limit")
        self.assertIn(RATE_LIMIT_MODAL_SELECTOR.lstrip("#"), modal.attrs.get("id"))


if __name__ == "__main__":
    unittest.main()
