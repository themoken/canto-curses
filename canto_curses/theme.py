# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto.encoding import encoder, locale_enc
from widecurse import waddch, wcwidth

import curses

import logging

log = logging.getLogger("WIDECURSE")

attr_count = { "B" : 0,
               "D" : 0,
               "R" : 0,
               "S" : 0,
               "U" : 0 }

# theme_print handles attribute codes and escaping:
#   %1 - %8 turns on color pairs 1 - 8
#   %0      turns on the previously enabled color

color_stack = []

# Return length of next string of non-space characters
# or 0 if next character *is* a space.

def len_next_word(uni):
    if ' ' in uni:
        return theme_len(uni.split(' ', 1)[0])
    return theme_len(uni)

class FakePad():
    def __init__(self, width):
        self.x = 0
        self.y = 0
        self.width = width

    def attron(self, attr):
        pass

    def attroff(self, attr):
        pass

    def waddch(self, ch):
        self.x += wcwidth(ch)
        if self.x >= self.width:
            self.y += 1
            self.x -= self.width

    def getyx(self):
        return (self.y, self.x)

    def move(self, y, x):
        self.y = y
        self.x = x

class WrapPad():
    def __init__(self, pad):
        self.pad = pad

    def attron(self, attr):
        self.pad.attron(attr)

    def attroff(self, attr):
        self.pad.attroff(attr)

    def waddch(self, ch):
        waddch(self.pad, ch)

    def getyx(self):
        return self.pad.getyx()

    def move(self, x, y):
        return self.pad.move(x, y)

def theme_print(pad, uni, width):
    global color_stack
    global attr_count

    max_width = width
    escaped = False
    code = False

    for i, c in enumerate(uni):
        ec = encoder(c)
        if escaped:
            # No room
            cwidth = wcwidth(ec)
            if cwidth > width:
                return "\\" + uni[i:]

            pad.waddch(ec)
            width -= cwidth
            escaped = False
        elif code:
            # Turn on color 1 - 8
            if c in "12345678":
                color_stack.append(ord(c) - ord('0'))
                pad.attron(curses.color_pair(color_stack[-1]))

            # Return to previous color
            elif c == '0':
                if len(color_stack) >= 2:
                    pad.attron(curses.color_pair(color_stack[-2]))
                    color_stack = color_stack[0:-1]
                else:
                    pad.attron(curses.color_pair(0))
            elif c in "BbDdRrSsUu":
                if c.isupper():
                    attr_count[c] += 1
                else:
                    c = c.upper()
                    attr_count[c] -= 1

                if c == "B":
                    a = curses.A_BOLD
                elif c == "D":
                    a = curses.A_DIM
                elif c == "R":
                    a = curses.A_REVERSE
                elif c == "S":
                    a = curses.A_STANDOUT
                elif c == "U":
                    a = curses.A_UNDERLINE

                if attr_count[c]:
                    pad.attron(a)
                else:
                    pad.attroff(a)

            code = False
        elif c == "\\":
            escaped = True
        elif c == "%":
            code = True
        else:
            if c == " ":
                # Word too long
                wwidth = len_next_word(uni[i + 1:])

                # >= to account for current character
                if wwidth <= max_width and wwidth >= width:
                    return uni[i + 1:]

            cwidth = wcwidth(ec)

            # Character too long (should be handled above).
            if cwidth > width:
                return uni[i:]

            pad.waddch(ec)
            width -= cwidth

    return None

# Returns the effective, printed length of a string, taking
# escapes and wide characters into account.

def theme_len(uni):
    escaped = False
    code = False
    length = 0

    for c in uni:
	ec = encoder(c)
        if escaped:
            length += wcwidth(ec)
            escaped = False
        elif code:
            code = False
        elif c == "\\":
            escaped = True
        elif c == "%":
            code = True
        else:
            width = wcwidth(ec)
            if width >= 0:
                length += width
    return length
