# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from command import command_format
from theme import FakePad, WrapPad, theme_print
from html import htmlparser
from common import GuiBase

import logging
import curses

log = logging.getLogger("READER")

class Reader(GuiBase):
    def init(self, pad, callbacks):
        self.pad = pad

        self.offset = 0
        self.max_offset = 0
        self.saved = {}
        self.waiting_on_content = False

        self.callbacks = callbacks
        self.keys = {
            " " : "destroy",
            "d" : "toggle-opt reader.show_description",
            "l" : "toggle-opt reader.enumerate_links",
            "g" : "goto",
            curses.KEY_DOWN : "scroll-down",
            curses.KEY_UP : "scroll-up",
            curses.KEY_NPAGE : "page-down",
            curses.KEY_PPAGE : "page-up"
        }

    def refresh(self):
        self.height, self.width = self.pad.getmaxyx()
        show_desc = self.callbacks["get_opt"]("reader.show_description")
        enum_links = self.callbacks["get_opt"]("reader.enumerate_links")

        save = { "desc" : show_desc,
                 "enum" : enum_links,
                 "offset" : self.offset }

        # Particulars have changed, re-render.
        if self.saved != save or self.waiting_on_content:
            self.saved = save

            fp = FakePad(self.width)
            lines = self.render(fp, show_desc, enum_links)

            # Create pre-rendered pad
            self.fullpad = curses.newpad(lines + 1, self.width)
            self.render(WrapPad(self.fullpad), show_desc, enum_links)

            # Update offset based on new display properties.
            self.max_offset = max(lines - self.height, 0)
            self.offset = min(self.offset, self.max_offset)

        # Overwrite visible pad with relevant area of pre-rendered pad.
        self.pad.erase()
        self.fullpad.overwrite(self.pad, self.offset, 0, 0, 0,\
                min(self.height,self.fullpad.getmaxyx()[0]) - 1, self.width - 1)

        self.callbacks["refresh"]()

    def redraw(self):
        self.refresh()

    def render(self, pad, show_description, enumerate_links):
        self.links = []

        s = "No selected story.\n"

        sel = self.callbacks["get_var"]("reader_item")
        if sel:
            self.links = [("link",sel.content["link"],"mainlink")]

            s = "%B" + sel.content["title"] + "%b\n"

            # We use the description for most reader content, so if it hasn't
            # been fetched yet then grab that from the server now and set
            # needs_deferred_redraw so that we consistently get re-called until
            # description appears thanks to the ATTRIBUTES response.

            if "description" not in sel.content:
                self.callbacks["write"]("ATTRIBUTES",\
                        { sel.id : ["description" ] })
                self.callbacks["set_var"]("needs_deferred_redraw", True)
                s += "%BWaiting for content...%b\n"
                self.waiting_on_content = True
            else:
                self.waiting_on_content = False
                content, links =\
                        htmlparser.convert(sel.content["description"])

                # 0 always is the mainlink, append other links
                # to the list.

                self.links += links

                if show_description:
                    s += content

                if enumerate_links:
                    s += "\n\n"

                    for idx, (t, url, text) in enumerate(self.links):
                        link_text = "[%B" + unicode(idx) + "%b][" +\
                                text + "]: " + url + "\n\n"

                        if t == "link":
                            link_text = "%5" + link_text + "%0"
                        elif t == "img":
                            link_text = "%4" + link_text + "%0"

                        s += link_text

        lines = 0
        while s:
            s = s.lstrip(" \t\v").rstrip(" \t\v")
            s = theme_print(pad, s, self.width, " ", " ")
            lines += 1

        return lines

    def eprompt(self, prompt):
        return self._cfg_set_prompt("reader.enumerate_links", "links: ")

    def listof_links(self, args):
        ints = self._listof_int(args, len(self.links),\
                lambda : self.eprompt("links: "))
        return (True, [ self.links[i] for i in ints ], "")

    @command_format([("links", "listof_links")])
    def cmd_goto(self, **kwargs):
        # link = ( type, url, text ) 
        links = [ l[1] for l in kwargs["links"] ]
        self._goto(links)

    @command_format([])
    def cmd_scroll_up(self, **kwargs):
        self._relscroll(-1)

    @command_format([])
    def cmd_scroll_down(self, **kwargs):
        self._relscroll(1)

    @command_format([])
    def cmd_page_up(self, **kwargs):
        self._relscroll(-1 * (self.height - 1))

    @command_format([])
    def cmd_page_down(self, **kwargs):
        self._relscroll(self.height - 1)

    def _relscroll(self, factor):
        log.debug("relscroll: %d" % factor)
        log.debug("maxoffset: %d" % self.max_offset)
        self.offset = self.offset + factor
        self.offset = min(self.offset, self.max_offset)
        self.offset = max(self.offset, 0)
        self.callbacks["set_var"]("needs_redraw", True)
        log.debug("-->: %d" % self.offset)

    def is_input(self):
        return False

    def get_opt_name(self):
        return "reader"

    def get_height(self, mheight):
        return mheight

    def get_width(self, mwidth):
        return mwidth
