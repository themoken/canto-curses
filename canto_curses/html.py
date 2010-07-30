# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from HTMLParser import HTMLParser
import htmlentitydefs
import re

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
        if self.verbatim <= 0:
            text = text.replace(u"\n", u" ")

        if self.link_open:
            log.debug("adding %s to link_text" % text)
            self.link_text += text

        self.result += text

    def convert_charref(self, ref):
        try:
            if ref[0] in [u'x',u'X']:
                c = int(ref[1:], 16)
            else:
                c = int(ref)
        except:
            return u"[?]"
        return unichr(c)

    def handle_charref(self, ref):
        self.result += self.convert_charref(ref)

    def convert_entityref(self, ref):
        if ref in htmlentitydefs.name2codepoint:
            return unichr(htmlentitydefs.name2codepoint[ref])
        return u"[?]"

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
                self.result += "%5"
            else:
                self.links.append(("link", self.link_href, self.link_text))
                self.link_text = ""
                self.link_href = ""
                self.link_open = False
                self.result += "%0"

        elif tag in ["img"]:
            if open:
                if "src" not in attrs:
                    return
                if "alt" not in attrs:
                    attrs["alt"] = ""
                self.handle_data("%4" + attrs["alt"] + "%0")
                self.links.append(("image", attrs["src"], attrs["alt"]))

        elif tag in [u"h" + unicode(x) for x in xrange(1,7)]:
            if open:
                self.result += u"\n%B"
            else:
                self.result += u"%b\n"
        elif tag in [u"blockquote"]:
            if open:
                self.result += u"\n%Q"
            else:
                self.result += u"%q\n"
        elif tag in [u"pre",u"code"]:
            if open:
                if tag == u"pre":
                    self.result += u"\n%Q"
                self.verbatim += 1
            else:
                if tag == u"pre":
                    self.result += u"%q\n"
                self.verbatim -= 1
        elif tag in [u"sup"]:
            if open:
                self.result += u"^"
        elif tag in [u"p", u"br", u"div"]:
            self.result += u"\n"
        elif tag in [u"ul", u"ol"]:
            if open:
                self.result += u"\n%I"
                self.list_stack.append([tag,0])
            else:
                # Grumble grumble. Bad HTML.
                if len(self.list_stack):
                    self.list_stack.pop()
                self.result += u"%i\n"
        elif tag in [u"li"]:
            if open:
                self.result += u"\n"

                # List item with no start tag, default to ul
                if not len(self.list_stack):
                    self.list_stack.append(["ul",0])

                if self.list_stack[-1][0] == u"ul":
                    self.result += u"\u25CF "
                else:
                    self.list_stack[-1][1] += 1
                    self.result += unicode(self.list_stack[-1][1])+ ". "
            else:
                self.result += u"\n"

        elif tag in [u"i", u"small", u"em"]:
            if open:
                self.result += u"%6%B"
            else:
                self.result += u"%b%0"
        elif tag in [u"b", u"strong"]:
            if open:
                self.result += u"%B"
            else:
                self.result += u"%b"

    def ent_wrapper(self, match):
        return self.convert_entityref(match.groups()[0])

    def char_wrapper(self, match):
        return self.convert_charref(match.groups()[0])

    def convert(self, s):
        # We have this try except because under no circumstances
        # should the HTML parser crash the application. Better
        # handling is done per case in the handler itself so that
        # bad HTML doesn't necessarily lead to garbage output.

        self.feed(s)

        r = self.result
        l = self.links
        self.reset()

        return (r,l)

htmlparser = CantoHTML()

html_entity_regex = re.compile(u"&(\w{1,8});")

def html_entity_convert(s):
    return html_entity_regex.sub(htmlparser.ent_wrapper, s)

char_ref_regex = re.compile(u"&#([xX]?[0-9a-fA-F]+)[^0-9a-fA-F]")

def char_ref_convert(s):
    return char_ref_regex.sub(htmlparser.char_wrapper, s)
