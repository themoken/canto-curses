# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

# XXX Code moved from old canto XXX

# I am aware that Python's curses library comes with a TextBox class
# and, indeed, the input() function was using it for awhile. The problems
# with Textbox were numerous though:
#   * Only ASCII characters could be printed/inputted (the *big* one)
#   * Included a whole bunch of multi-line editing and validation stuff
#       that was completely unnecessary, since we know the input line
#       only needs to be one line long.
#   * To make editing easier, it used a half-ass system of gathering
#       the data from the window's written content with win.inch(),
#       which apparently didn't play nice with multi-byte?
#
# All of these problems have been fixed in half as many lines with all
# the same functionality on a single line basis, but the design is still
# based on Textbox.

from canto_next.encoding import encoder
from common import GuiBase

import logging
log = logging.getLogger("INPUT")

import curses
from curses import ascii

class InputBox(GuiBase):
    def init(self, pad, callbacks):
        self.pad = pad

        self.callbacks = callbacks

        self.keys = {}

        self.reset()

    def reset(self, prompt_str=None):
        self.pad.erase()
        if prompt_str:
            self.pad.addstr(prompt_str)
        self.minx = self.pad.getyx()[1]
        self.x = self.minx
        self.result = ""

    def refresh(self):
        self.pad.move(0, self.minx)
        maxx = self.pad.getmaxyx()[1]
        try:
            self.pad.addstr(encoder(self.result[-1 * (maxx - self.minx):]))
        except:
            pass
        self.pad.clrtoeol()
        self.pad.move(0, min(self.x, maxx - 1))
        self.callbacks["refresh"]()

    def redraw(self):
        self.refresh()

    def addkey(self, ch):
        if ch in (ascii.STX, curses.KEY_LEFT):
            if self.x > self.minx:
                self.x -= 1
        elif ch in (ascii.BS, curses.KEY_BACKSPACE):
            if self.x > self.minx:
                idx = self.x - self.minx
                self.result = self.result[:idx - 1] + self.result[idx:]
                self.x -= 1
        elif ch in (ascii.ACK, curses.KEY_RIGHT): # C-f
            self.x += 1
            if len(self.result) + self.minx < self.x:
                self.result += " "
        elif ch in (ascii.ENQ, curses.KEY_END): # C-e
            self.x = self.minx + len(self.result)
        elif ch in (ascii.SOH, curses.KEY_HOME): # C-a
            self.x = self.minx
        elif ch == ascii.NL: # C-j
            return 0
        elif ch == ascii.BEL: # C-g
            self.result = ""
            return 0
        else:
            self.x += 1
            idx = self.x - self.minx
            self.result = self.result[:idx] + unichr(ch) + self.result[idx:]

        self.refresh()
        curses.doupdate()
        return 1

    def edit(self, prompt=":"):
        # Render initial prompt
        self.reset(prompt)
        self.refresh()
        curses.doupdate()

    def is_input(self):
        return True

    def get_opt_name(self):
        return "input"

    def get_height(self, mheight):
        return 1

    def get_width(self, mwidth):
        return mwidth
