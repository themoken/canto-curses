# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.encoding import encoder, locale_enc
from widecurse import waddch, wcwidth

import curses

import logging

log = logging.getLogger("WIDECURSE")

attr_count = { "B" : 0,
               "D" : 0,
               "R" : 0,
               "S" : 0,
               "U" : 0 }

attr_map = { "B" : curses.A_BOLD,
             "D" : curses.A_DIM,
             "R" : curses.A_REVERSE,
             "S" : curses.A_STANDOUT,
             "U" : curses.A_UNDERLINE }

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

    def clrtoeol(self):
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

    def clrtoeol(self):
        self.pad.clrtoeol()

    def waddch(self, ch):
        waddch(self.pad, ch)

    def getyx(self):
        return self.pad.getyx()

    def move(self, x, y):
        return self.pad.move(x, y)

def theme_print_one(pad, uni, width):
    global color_stack
    global attr_count
    global attr_map

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

            # Turn attributes on / off
            elif c in "BbDdRrSsUu":
                if c.isupper():
                    attr_count[c] += 1
                else:
                    c = c.upper()
                    attr_count[c] -= 1

                if attr_count[c]:
                    pad.attron(attr_map[c])
                else:
                    pad.attroff(attr_map[c])

            # Suspend attributes
            elif c == "C":
                for attr in attr_map:
                    pad.attroff(attr_map[attr])

            # Restore attributes
            elif c == "c":
                for attr in attr_map:
                    if attr_count[attr]:
                        pad.attron(attr_map[attr])

            code = False
        elif c == "\\":
            escaped = True
        elif c == "%":
            code = True
        elif c == "\n":
            return uni[i + 1:]
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

def theme_print(pad, uni, mwidth, pre = "", post = "", cursorbash=True):
    prel = theme_len(pre)
    postl = theme_len(post)
    y = pad.getyx()[0]

    theme_print_one(pad, pre, prel)

    width = (mwidth - prel) - postl
    if width <= 0:
        raise Exception("theme_print: NO ROOM!")

    r = theme_print_one(pad, uni, width)

    pad.clrtoeol()

    if post:
        pad.move(y, mwidth - postl)
        theme_print_one(pad, post, postl)

    if cursorbash:
        try:
            pad.move(y + 1, 0)
        except:
            pass

    if r == uni:
        raise Exception("theme_print: didn't advance!")

    return r

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

# This is useful when a themed string needs to get truncated, so that color and
# attribute settings can be processed, despite the last part of the string not
# being displayed.

def theme_process(pad, uni):
    only_codes = ""
    escaped = False
    code = False

    for c in uni:
        if escaped:
            escaped = False
            continue
        elif code:
            only_codes += c
            code = False
        elif c == "\\":
            escaped = True
        elif c == "%":
            code = True
            only_codes += "%"

    # NOTE: len works because codes never use widechars.
    theme_print(pad, only_codes, len(only_codes), "", "", False)

# Strip more than two newlines from the front of the input, processing escapes
# as we discard characters.

def theme_lstrip(pad, uni):
    newlines = 0
    codes = u""
    escaped = False

    for i, c in enumerate(uni):
        # Discard
        if c in " \t\v":
            continue

        if c == "\n":
            newlines = 1
        elif c == "%":
            escaped = True
            codes += "%"
        elif escaped:
            escaped = False
            codes += c
        else:
            r = uni[i:]
            break

    # No content found.
    else:
        newlines = 0
        r = ""

    # Process dangling codes.
    if codes:
        theme_process(pad, codes)

    return (newlines * "\n") + r
