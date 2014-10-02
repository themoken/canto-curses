# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2014 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import Plugin
from .guibase import GuiBase
from .widecurse import get_rlpoint

import logging
log = logging.getLogger("INPUT")

import readline
import curses
from curses import ascii

class InputPlugin(Plugin):
    pass

class InputBox(GuiBase):
    def __init__(self):
        GuiBase.__init__(self)
        self.plugin_class = InputPlugin

    def init(self, pad, callbacks):
        self.pad = pad

        self.callbacks = callbacks

        self.reset()

    def reset(self):
        self.pad.erase()
        self.pad.addstr(self.callbacks["get_var"]("input_prompt"))
        self.minx = self.pad.getyx()[1]
        self.x = self.minx
        self.content = readline.get_line_buffer()

        # Part that's not considered
        self.completion_root = None
        self.completions = None

    def rotate_completions(self, sub, matches):
        log.debug("rotate: %s %s" % (sub, matches))
        log.debug("rotate_content: %s" % self.content)

        comproot = self.callbacks["get_var"]("input_completion_root")
        complist = self.callbacks["get_var"]("input_completions")

        if self.content != comproot or not complist:
            log.debug("setting root: %s" % self.content)
            log.debug("setting comps: %s" % [x[len(sub):] for x in matches])
            self.callbacks["set_var"]("input_completion_root", self.content)
            self.callbacks["set_var"]("input_completions", [x[len(sub):] for x in matches])
        else:
            complist = [complist[-1]] + complist[:-1]
            log.debug("complist: %s" % complist)
            self.callbacks["set_var"]("input_completions", complist)

    def break_completion(self):
        log.debug("COMPLETION BROKEN")
        comp = self.callbacks["get_var"]("input_completions")
        self.callbacks["set_var"]("input_completions", [])
        self.callbacks["set_var"]("input_completion_root", "")
        if comp:
            return comp[0]
        return None

    def set_content(self, s):
        self.content = s

    def refresh(self):
        self.pad.move(0, self.minx)
        maxx = self.pad.getmaxyx()[1]

        s = self.content
        complist = self.callbacks["get_var"]("input_completions")
        if complist:
            s += complist[0]

        log.debug("printing: '%s'" % s[-1 * (maxx - self.minx):])
        try:
            self.pad.addstr(s[-1 * (maxx - self.minx):])
        except:
            pass
        self.x = self.pad.getyx()[1]
        self.pad.clrtoeol()
        self.pad.move(0, self.minx + get_rlpoint())
        self.callbacks["refresh"]()

    def redraw(self):
        pass

    def is_input(self):
        return True

    def get_opt_name(self):
        return "input"

    def get_height(self, mheight):
        return 1

    def get_width(self, mwidth):
        return mwidth
