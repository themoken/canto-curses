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

import logging
log = logging.getLogger("INPUT")

import curses
from curses import ascii

class InputBox:
    def init(self, pad, refresh_callback, coords):
        self.pad = pad
        self.pad.keypad(1)
        self.coords = coords
        self.refresh_callback = refresh_callback
        self.reset()

    def reset(self, prompt_char=None):
        self.pad.erase()
        if prompt_char:
            self.pad.addch(prompt_char)
        self.minx = self.pad.getyx()[1]
        self.x = self.minx
        self.result = ""

    def get_height(self):
        return 1

    def refresh(self):
        self.pad.move(0, self.minx)
        maxx = self.pad.getmaxyx()[1]
        try:
            self.pad.addstr(self.result[-1 * (maxx - self.minx):]\
                    .encode("UTF-8", "replace"))
        except:
            pass
        self.pad.clrtoeol()
        self.pad.move(0, min(self.x, maxx - 1))
        self.refresh_callback(self.coords)

    def key(self, ch):
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
            return -1
        elif ch == ascii.FF: # C-l
            self.refresh()
        else:
            self.x += 1
            idx = self.x - self.minx
            self.result = self.result[:idx] + unichr(ch) + self.result[idx:]
        return 1

    def edit(self):
        self.reset(":")
        while 1:
            ch = self.pad.getch()
            if ch <= 0:
                continue
            r = self.key(ch)
            if not r:
                break
            if r < 0:
                self.result = None
                break
            self.refresh()
            curses.doupdate()
        return self.result

