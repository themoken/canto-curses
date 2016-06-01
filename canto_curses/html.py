# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2016 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from html.parser import HTMLParser
import html.entities
import re

from .color import cc

import logging

log = logging.getLogger("HTML")

class CantoHTML(HTMLParser):

    # Reset is used, instead of __init__ so a single
    # instance of the class can parse multiple HTML
    # fragments.

    def reset(self):
        HTMLParser.reset(self)
        self.result = ""
        self.list_stack = []
        self.verbatim = 0

        self.links = []
        self.link_text = ""
        self.link_href = ""
        self.link_open = False

    # unknown_* funnel all tags to handle_tag

    def handle_starttag(self, tag, attrs):
        self.handle_tag(tag, attrs, 1)

    def handle_endtag(self, tag):
        self.handle_tag(tag, {}, 0)

    def handle_data(self, text):
        self.handle_data_clean(text.replace("\\","\\\\",).replace("%","\\%"))

    def handle_data_clean(self, text):
        if self.verbatim <= 0:
            text = text.replace("\n", " ")

        if self.link_open:
            log.debug("adding %s to link_text", text)
            self.link_text += text

        self.result += text

    def convert_charref(self, ref):
        try:
            if ref[0] in ['x','X']:
                c = int(ref[1:], 16)
            else:
                c = int(ref)
        except:
            return ref
        return chr(c)

    def handle_charref(self, ref):
        self.result += self.convert_charref(ref)

    def convert_entityref(self, ref):
        if ref in html.entities.name2codepoint:
            return chr(html.entities.name2codepoint[ref])
        return "[?]"

    def handle_entityref(self, ref):
        self.result += self.convert_entityref(ref)

    # This is the real workhorse of the HTML parser.

    def attr_dict(self, attrs):
        d = {}
        for k, v in attrs:
            d[k] = v
        return d
    
    def handle_tag(self, tag, attrs, open):
        # Convert attrs (list of two-tuples) to dict.
        attrs = self.attr_dict(attrs)

        if tag in ["a"]:
            if open:
                if "href" not in attrs:
                    return
                self.link_open = True
                self.link_href = attrs["href"]
                self.result += cc("reader_link")
            else:
                self.links.append(("link", self.link_href, self.link_text))
                self.link_text = ""
                self.link_href = ""
                self.link_open = False
                self.result += "[" + str(len(self.links)) + "]" + cc.end("reader_link")

        elif tag in ["img"]:
            if open:
                if "src" not in attrs:
                    return
                if "alt" not in attrs:
                    attrs["alt"] = ""
                self.links.append(("image", attrs["src"], attrs["alt"]))
                self.handle_data_clean(cc("reader_image_link") + attrs["alt"] +\
                        "[" + str(len(self.links)) + "]" + cc.end("reader_image_link"))

        elif tag in ["h" + str(x) for x in range(1,7)]:
            if open:
                self.result += "\n%B"
            else:
                self.result += "%b\n"
        elif tag in ["blockquote"]:
            if open:
                self.result += "\n%Q"
            else:
                self.result += "%q\n"
        elif tag in ["pre","code"]:
            if open:
                if tag == "pre":
                    self.result += "\n%Q"
                self.verbatim += 1
            else:
                if tag == "pre":
                    self.result += "%q\n"
                self.verbatim -= 1
        elif tag in ["sup"]:
            if open:
                self.result += "^"
        elif tag in ["p", "br", "div"]:
            self.result += "\n"
        elif tag in ["ul", "ol"]:
            if open:
                self.result += "\n%I"
                self.list_stack.append([tag,0])
            else:
                # Grumble grumble. Bad HTML.
                if len(self.list_stack):
                    self.list_stack.pop()
                self.result += "%i\n"
        elif tag in ["li"]:
            if open:
                self.result += "\n"

                # List item with no start tag, default to ul
                if not len(self.list_stack):
                    self.list_stack.append(["ul",0])

                if self.list_stack[-1][0] == "ul":
                    self.result += "\u25CF "
                else:
                    self.list_stack[-1][1] += 1
                    self.result += str(self.list_stack[-1][1])+ ". "
            else:
                self.result += "\n"

        elif tag in ["i", "small", "em"]:
            if open:
                self.result += cc("reader_italics")
            else:
                self.result += cc.end("reader_italics")
        elif tag in ["b", "strong"]:
            if open:
                self.result += "%B"
            else:
                self.result += "%b"

    def ent_wrapper(self, match):
        return self.convert_entityref(match.groups()[0])

    def char_wrapper(self, match):
        return self.convert_charref(match.groups()[0])

    def convert(self, s):
        # We have this try except because under no circumstances
        # should the HTML parser crash the application. Better
        # handling is done per case in the handler itself so that
        # bad HTML doesn't necessarily lead to garbage output.

        try:
            self.feed(s)
        except Exception as e:
            r = "Error Parsing Content:\n\n"
            r += ("%s" % e)
            l = []
        else:
            r = self.result
            l = self.links

        self.reset()
        return (r,l)

htmlparser = CantoHTML()

html_entity_regex = re.compile("&(\w{1,8});")

def html_entity_convert(s):
    return html_entity_regex.sub(htmlparser.ent_wrapper, s)

char_ref_regex = re.compile("&#([xX]?[0-9a-fA-F]+)[^0-9a-fA-F]")

def char_ref_convert(s):
    return char_ref_regex.sub(htmlparser.char_wrapper, s)
