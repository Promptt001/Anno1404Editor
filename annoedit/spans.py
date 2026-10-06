#!/usr/bin/env python3
"""spans — a child-axis, offset-preserving XML index.

A regex that matches <tag> anywhere inside a parent's text walks the
DESCENDANT axis: a link missing at the right depth gets silently satisfied
by a same-name tag deeper down. Edits must walk the CHILD axis instead.

This module indexes XML text into a Node tree where every node knows its
byte spans, and every lookup walks DIRECT children only:

    root = index(text)                # -> Node for the whole fragment
    child(root, "Military")           # -> [direct children named Military]
    text_span(node)                   # -> (inner_start, inner_end)

Editing stays BYTE SPLICES: spans locate the node to rewrite; everything
outside the rewritten span is untouched, CRLF preserved, never re-serialized.

Tokenizer handles: <!-- comments -->, <![CDATA[...]]>, <?processing?>,
</close>, <self-closed/>, <open>. SpanError (never guesses) on a mismatched
close or unexpected EOF.

Works on str (aiprofiles.xml is ASCII/UTF-8; the profiles engine never
touches the cp1252 files — extras/fertility keep their own editors).
"""
import re


class SpanError(Exception):
    """Malformed XML structure while indexing (mismatched close, EOF)."""


class Node:
    """One XML element with absolute spans into the indexed text."""

    __slots__ = ("tag", "open_start", "open_end", "close_start",
                 "close_end", "self_closed", "children", "parent")

    def __init__(self, tag, open_start, open_end, close_start, close_end,
                 self_closed, parent):
        self.tag = tag
        self.open_start = open_start   # '<' of the opening tag
        self.open_end = open_end       # '>' of the opening tag
        self.close_start = close_start  # '<' of </tag> (0 if self-closed)
        self.close_end = close_end     # '>' of </tag> (== open_end if self-closed)
        self.self_closed = self_closed
        self.children = []
        self.parent = parent

    def __repr__(self):
        kind = "self-closed" if self.self_closed else "open"
        return f"<Node {self.tag} {kind} @{self.open_start}>"

    @property
    def start(self):
        """Absolute start of the whole element."""
        return self.open_start

    @property
    def end(self):
        """Absolute end of the whole element."""
        return self.close_end


_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9.-]*")
# Precompiled patterns used with .match(text, pos, end), which avoids
# copying the remaining text for every tag.
_CLOSE_RE = re.compile(r"</\s*([A-Za-z_][A-Za-z_0-9.-]*)\s*>")
_OPEN_RE = re.compile(r"<\s*([A-Za-z_][A-Za-z_0-9.-]*)")


def index(text, start=0, end=None, fragment=True):
    """Index text[start:end] into a synthetic root Node.

    The returned root's `children` are the top-level elements of the
    fragment. Raises SpanError on mismatched closes or unexpected EOF.
    """
    if end is None:
        end = len(text)
    root = Node("#root", start, start, end, end, False, None)
    stack = [root]
    i = start
    while i < end:
        lt = text.find("<", i, end)
        if lt < 0:
            break
        if text.startswith("<!--", lt):
            close = text.find("-->", lt, end)
            if close < 0:
                if not fragment:
                    raise SpanError(f"unterminated comment at {lt}")
                break
            i = close + 3
            continue
        if text.startswith("<![CDATA[", lt):
            close = text.find("]]>", lt, end)
            if close < 0:
                if not fragment:
                    raise SpanError(f"unterminated CDATA at {lt}")
                break
            i = close + 3
            continue
        if text.startswith("<?", lt):
            close = text.find("?>", lt, end)
            if close < 0:
                if not fragment:
                    raise SpanError(f"unterminated PI at {lt}")
                break
            i = close + 2
            continue
        if text.startswith("</", lt):
            m = _CLOSE_RE.match(text, lt, end)
            if not m:
                if not fragment:
                    raise SpanError(f"malformed close tag at {lt}")
                break
            tag = m.group(1)
            gt = m.end()  # positional match: already an absolute offset
            top = stack[-1]
            if top.tag != tag:
                raise SpanError(
                    f"mismatched close </{tag}> at {lt}: open element is "
                    f"<{top.tag}> (opened at {top.open_start})")
            stack.pop()
            top.close_start, top.close_end = lt, gt
            i = gt
            continue
        m = _OPEN_RE.match(text, lt, end)
        if not m:
            # stray '<' that is not markup (or a malformed tag) — skip it
            i = lt + 1
            continue
        tag = m.group(1)
        # Find the end of the tag, respecting quoted attributes.
        j = m.end()
        self_closed = False
        while j < end:
            ch = text[j]
            if ch in "\"'":
                k = text.find(ch, j + 1, end)
                if k < 0:
                    raise SpanError(f"unterminated quote in <{tag}> at {lt}")
                j = k + 1
            elif ch == ">":
                break
            elif ch == "/" and text.startswith("/>", j):
                self_closed = True
                j += 2
                break
            else:
                j += 1
        else:
            if not fragment:
                raise SpanError(f"unexpected EOF inside <{tag}> at {lt}")
            break
        if j >= end:
            if not fragment:
                raise SpanError(f"unexpected EOF inside <{tag}> at {lt}")
            break
        open_end = j + 1 if not self_closed else j  # '>' (or '/' end)
        if self_closed:
            node = Node(tag, lt, j, lt, j, True, stack[-1])
            node.close_end = j
            stack[-1].children.append(node)
            i = j
            continue
        node = Node(tag, lt, open_end, -1, -1, False, stack[-1])
        stack[-1].children.append(node)
        stack.append(node)
        i = open_end
    if len(stack) > 1 and not fragment:
        raise SpanError(f"unclosed element <{stack[-1].tag}> "
                        f"(opened at {stack[-1].open_start})")
    return root


def child(node, tag):
    """Direct children of `node` with the given tag (CHILD axis only)."""
    return [c for c in node.children if c.tag == tag]


def text_span(node):
    """(inner_start, inner_end): the text between the opening and closing
    tags. For a self-closed node the span is empty (start == end)."""
    if node.self_closed:
        return node.open_end, node.open_end
    # An unclosed fragment node (close_start == -1) has no inner span;
    # slicing [open_end:-1] would silently drop its tail.
    if node.close_start < 0:
        raise SpanError(f"text_span of an unclosed <{node.tag}> "
                        "node (fragment mode never closes it)")
    return node.open_end, node.close_start
