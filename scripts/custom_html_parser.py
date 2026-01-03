#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from html.parser import HTMLParser
from typing import Optional


class MyHTMLParser(HTMLParser):
    def __init__(self):
        # Initialize internal state before calling super
        self.tags: list[str] = []
        super().__init__(convert_charrefs=True)

    def clear(self):
        """Resets the parser and clears the stored tags."""
        self.reset()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        # Ignore specific tags
        if tag == "br":
            return

        attr_list = []
        for name, value in sorted(attrs, key=lambda x: x[0]):
            if name in {"{", "}"}:
                continue

            if name == "alt":
                value = "-"

            attr_str = f' {name}="{value}"' if value is not None else f" {name}"
            attr_list.append(attr_str)

        attributes_str = "".join(attr_list)
        self.tags.append(f"<{tag}{attributes_str}>")

    def handle_endtag(self, tag: str) -> None:
        if tag != "br":
            self.tags.append(f"</{tag}>")

    def get_tags(self) -> list[str]:
        return self.tags
