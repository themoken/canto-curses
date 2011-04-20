# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import Plugin
from canto_next.hooks import on_hook, remove_hook

from theme import FakePad, WrapPad, theme_print, theme_lstrip
from command import command_format
from html import htmlparser
from guibase import GuiBase

import logging
import curses
import re

log = logging.getLogger("READER")

class ReaderPlugin(Plugin):
    pass

class Reader(GuiBase):
    def __init__(self):
        GuiBase.__init__(self)
        self.plugin_class = ReaderPlugin

    def init(self, pad, callbacks):
        self.pad = pad

        self.max_offset = 0

        self.callbacks = callbacks

        self.quote_rgx = re.compile(u"[\\\"](.*?)[\\\"]")

        on_hook("opt_change", self.on_opt_change)

    def die(self):
        remove_hook("opt_change", self.on_opt_change)

    def on_opt_change(self, change):
        if "reader.show_description" in change or\
                "reader.enumerate_links" in change:
            self.refresh()

    def on_attributes(self, attributes):
        sel = self.callbacks["get_var"]("reader_item")
        if sel in attributes:
            remove_hook("attributes", self.on_attributes)

            # Don't bother checking attributes. If we're still
            # lacking, refresh  will re-enable this hook
            self.refresh()
            self.callbacks["set_var"]("needs_redraw", True)

    def refresh(self):
        self.height, self.width = self.pad.getmaxyx()
        show_desc = self.callbacks["get_opt"]("reader.show_description")
        enum_links = self.callbacks["get_opt"]("reader.enumerate_links")
        offset = self.callbacks["get_var"]("reader_offset")

        fp = FakePad(self.width)
        lines = self.render(fp, show_desc, enum_links)

        # Create pre-rendered pad
        self.fullpad = curses.newpad(lines, self.width)
        self.render(WrapPad(self.fullpad), show_desc, enum_links)

        # Update offset based on new display properties.
        self.max_offset = max((lines - 1) - (self.height - 1), 0)

        offset = min(offset, self.max_offset)
        self.callbacks["set_var"]("reader_offset", offset)

        self.redraw()

    def redraw(self):
        offset = self.callbacks["get_var"]("reader_offset")

        # Overwrite visible pad with relevant area of pre-rendered pad.
        self.pad.erase()

        realheight = min(self.height, self.fullpad.getmaxyx()[0]) - 1

        self.fullpad.overwrite(self.pad, offset, 0, 0, 0,\
                realheight, self.width - 1)

        self.pad.move(realheight, 0)
        self.callbacks["refresh"]()

    def render(self, pad, show_description, enumerate_links):
        self.links = []

        s = "No selected story.\n"

        sel = self.callbacks["get_var"]("reader_item")
        if sel:
            self.links = [("link",sel.content["link"],"mainlink")]

            s = "%1%B" + sel.content["title"] + "%b\n"

            # We use the description for most reader content, so if it hasn't
            # been fetched yet then grab that from the server now and setup
            # a hook to get notified when sel's attributes are changed.

            if "description" not in sel.content:
                self.callbacks["write"]("ATTRIBUTES",\
                        { sel.id : ["description" ] })
                s += "%BWaiting for content...%b\n"
                on_hook("attributes", self.on_attributes)
            else:
                content, links =\
                        htmlparser.convert(sel.content["description"])

                # 0 always is the mainlink, append other links
                # to the list.

                self.links += links

                if show_description:
                    s += self.quote_rgx.sub(u"%6\"\\1\"%0", content)

                if enumerate_links:
                    s += "\n\n"

                    for idx, (t, url, text) in enumerate(self.links):
                        link_text = "[%B" + unicode(idx) + "%b][" +\
                                text + "]: " + url + "\n\n"

                        if t == "link":
                            link_text = "%5" + link_text + "%0"
                        elif t == "image":
                            link_text = "%4" + link_text + "%0"

                        s += link_text

        # After we have generated the entirety of the content,
        # strip out any egregious spacing.

        s = s.rstrip(" \t\v\n")

        lines = 0
        while s:
            s = theme_lstrip(pad, s)
            if s:
                s = theme_print(pad, s, self.width, " ", " ")
                lines += 1

        # Return one extra line because the rest of the reader
        # code knows to avoid the dead cell on the bottom right
        # of every curses pad.

        return lines + 1

    def eprompt(self, prompt):
        return self._cfg_set_prompt("reader.enumerate_links", "links: ")

    def listof_links(self, args):
        ints = self._listof_int(args, 0, len(self.links),\
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
        offset = self.callbacks["get_var"]("reader_offset")
        offset += factor
        offset = min(offset, self.max_offset)
        offset = max(offset, 0)
        self.callbacks["set_var"]("reader_offset", offset)
        self.redraw()

    def is_input(self):
        return False

    def get_opt_name(self):
        return "reader"

    def get_height(self, mheight):
        return mheight

    def get_width(self, mwidth):
        return mwidth
