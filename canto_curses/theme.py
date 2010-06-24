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

# theme_print handles attribute codes and escaping:
#   %1 - %8 turns on color pairs 0 - 7
#   %0      turns on the previously enabled color

color_stack = []

def theme_print(pad, uni, width):
    global color_stack

    escaped = False
    code = False

    for i, c in enumerate(uni):
	ec = encoder(c)
        if escaped:
            # No room
            cwidth = wcwidth(ec)
            if cwidth > width:
                return "\\" + uni[i:]

            waddch(pad, ec)
            width -= cwidth
            escaped = False
        elif code:
            # Turn on color 1 - 8
            if c in "12345678":
                color_stack.append(ord(c) - ord('0'))
                pad.attron(curses.color_pair(color_stack[-1] - 1))

            # Return to previous color
            elif c == '0':
                if len(color_stack) >= 2:
                    pad.attron(curses.color_pair(color_stack[-2] - 1))
                    color_stack = color_stack[0:-1]
                else:
                    pad.attron(curses.color_pair(0))
            code = False
        elif c == "\\":
            escaped = True
        elif c == "%":
            code = True
        else:
            # No room
            cwidth = wcwidth(ec)
            if cwidth > width:
                return uni[i:]
            waddch(pad, ec)
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
