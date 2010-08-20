# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from command import CommandHandler, command_format, generic_parse_error
from theme import FakePad, WrapPad, theme_print
from html import htmlparser

import logging
import curses

log = logging.getLogger("READER")

class Reader(CommandHandler):
    def init(self, pad, callbacks):
        self.pad = pad
        self.callbacks = callbacks
        self.keys = {" " : "destroy"}

    def refresh(self):
        self.redraw()

    def redraw(self):
        self.pad.erase()

        mwidth = self.pad.getmaxyx()[1]
        pad = WrapPad(self.pad)

        sel = self.callbacks["get_var"]("selected")
        if not sel:
            self.pad.addstr("No selected story.")
        else:
            if "description" not in sel.content:
                self.callbacks["write"]("ATTRIBUTES", { sel.id : [
                    "description" ] } )
                self.callbacks["set_var"]("needs_deferred_redraw", True)
                s = "%BWaiting for content...%b"
            else:
                s = "%B" + sel.content["title"] + "%b\n"
                c, l = htmlparser.convert(sel.content["description"])
                s += c

            while s:
                s = s.lstrip(" \t\v").rstrip(" \t\v")
                s = theme_print(pad, s, mwidth, " ", " ")

        self.callbacks["refresh"]()

    @command_format("destroy", [])
    def destroy(self, **kwargs):
        self.callbacks["die"](self)

    def command(self, cmd):
        if cmd.startswith("destroy"):
            self.destroy(args=cmd)

    def is_input(self):
        return False

    def get_opt_name(self):
        return "reader"

    def get_height(self, mheight):
        return mheight

    def get_width(self, mwidth):
        return mwidth
