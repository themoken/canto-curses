# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2016 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import Plugin
from .guibase import GuiBase
from .widecurse import get_rlpoint
from .command import cmd_complete_info

import logging
log = logging.getLogger("INPUT")

import readline
import curses
import shlex
from curses import ascii

class InputPlugin(Plugin):
    pass

class InputBox(GuiBase):
    def __init__(self):
        GuiBase.__init__(self)
        self.plugin_class = InputPlugin
        self.pad = None

    def init(self, pad, callbacks):
        self.pad = pad

        self.callbacks = callbacks

        self.reset()

    def reset(self):
        self.pad.erase()
        self.pad.addstr(self.callbacks["get_var"]("input_prompt"))
        self.minx = self.pad.getyx()[1]
        self.x = self.minx

        # Part that's not considered
        self.completion_root = None
        self.completions = None

    def _get_prefix(self):
        buf = readline.get_line_buffer()
        if (not buf) or buf[-1].isspace():
            prefix = ""
        else:
            prefix = shlex.split(buf)[-1]
        return prefix

    def rotate_completions(self):
        complist = self.callbacks["get_var"]("input_completions")
        oldpref = self.callbacks["get_var"]("input_completion_root")

        prefix = self._get_prefix()
        if not complist or oldpref != prefix:
            r = cmd_complete_info()
            if not r or not r[2]:
                complist = []
            else:
                complist = [ x[len(prefix):] for x in r[2] if x.startswith(prefix) ]
                complist.sort()
        else:
            complist = complist[1:] + [ complist[0] ]

        self.callbacks["set_var"]("input_completions", complist)
        self.callbacks["set_var"]("input_completion_root", prefix)

    def break_completion(self):
        comp = self.callbacks["get_var"]("input_completions")
        self.callbacks["set_var"]("input_completions", [])
        self.callbacks["set_var"]("input_completion_root", "")
        if comp:
            return comp[0]
        return None

    def refresh(self):
        if not self.pad:
            return

        self.pad.move(0, self.minx)
        maxx = self.pad.getmaxyx()[1]

        s = readline.get_line_buffer()
        complist = self.callbacks["get_var"]("input_completions")
        if complist:
            s += complist[0]

        log.debug("printing: '%s'", s[-1 * (maxx - self.minx):])
        try:
            self.pad.addstr(s[-1 * (maxx - self.minx):])
        except:
            pass
        self.x = self.pad.getyx()[1]
        self.pad.clrtoeol()
        self.pad.move(0, min(maxx - 1, self.minx + get_rlpoint()))
        try:
            self.callbacks["refresh"]()
        except:
            pass

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
