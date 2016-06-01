# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2016 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.encoding import encoder, locale_enc
from .widecurse import waddch, wcwidth
from .html import html_entity_convert, char_ref_convert
from .config import config

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
color_stack_suspended = []

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
        cwidth = wcwidth(ch)
        if cwidth < 0 and not ch.is_space():
            return

        self.x += cwidth
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

    long_code = False
    lc = ""

    for i, c in enumerate(uni):
        ec = encoder(c)
        cwidth = wcwidth(ec)
        if cwidth < 0 and not ec.isspace():
            continue

        if escaped:
            # No room
            if cwidth > width:
                return "\\" + uni[i:]

            try:
                pad.waddch(ec)
            except:
                log.debug("Can't print escaped ec: %s in: %s", ec, uni)

            width -= cwidth
            escaped = False
        elif code:
            # Turn on color 1 - 8
            if c in "12345678":
                if len(color_stack):
                    pad.attroff(curses.color_pair(color_stack[-1]))
                color_stack.append(ord(c) - ord('0'))
                pad.attron(curses.color_pair(color_stack[-1]))
            # Return to previous color
            elif c == '0':
                if len(color_stack):
                    pad.attroff(curses.color_pair(color_stack[-1]))

                if len(color_stack) >= 2:
                    pad.attron(curses.color_pair(color_stack[-2]))
                    color_stack = color_stack[0:-1]
                else:
                    pad.attron(curses.color_pair(0))
                    color_stack = []

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
                for color in reversed(color_stack):
                    pad.attroff(curses.color_pair(color))
                pad.attron(curses.color_pair(0))
                color_stack_suspended = color_stack
                color_stack = []

            # Restore attributes
            elif c == "c":
                for attr in attr_map:
                    if attr_count[attr]:
                        pad.attron(attr_map[attr])
                color_stack = color_stack_suspended
                color_stack_suspended = []
                if color_stack:
                    pad.attron(curses.color_pair(color_stack[-1]))
                else:
                    pad.attron(curses.color_pair(0))
            elif c == "[":
                long_code = True
            code = False
        elif long_code:
            if c == "]":
                try:
                    long_color = int(lc)
                except:
                    log.error("Unknown long code: %s! Ignoring..." % lc)
                else:
                    if long_color < 1 or long_color > 256:
                        log.error("long color code must be >= 1 and <= 256")
                    else:
                        try:
                            pad.attron(curses.color_pair(long_color))
                            color_stack.append(long_color)
                        except:
                            log.error("Could not set pair. Perhaps need to set TERM='xterm-256color'?")
                long_code = False
                lc = ""
            else:
                lc += c
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

            # Character too long (should be handled above).
            if cwidth > width:
                return uni[i:]

            try:
                pad.waddch(ec)
            except Exception as e:
                log.debug("Can't print ec: %s in: %s", ec, repr(encoder(uni)))
                log.debug("Exception: %s", e)

            width -= cwidth

    return None

def theme_print(pad, uni, mwidth, pre = "", post = "", cursorbash=True, clear=True):
    prel = theme_len(pre)
    postl = theme_len(post)
    y = pad.getyx()[0]

    theme_print_one(pad, pre, prel)

    width = (mwidth - prel) - postl
    if width <= 0:
        raise Exception("theme_print: NO ROOM!")

    r = theme_print_one(pad, uni, width)

    if clear:
        pad.clrtoeol()

    if post:
        try:
            pad.move(y, (mwidth - postl))
        except:
            log.debug("move error: %d %d", y, mwidth - postl)
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

        cwidth = wcwidth(ec)
        if cwidth < 0 and not ec.isspace():
            continue

        if escaped:
            length += cwidth
            escaped = False
        elif code:
            code = False
        elif c == "\\":
            escaped = True
        elif c == "%":
            code = True
        else:
            width = cwidth
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
    codes = ""
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

def theme_reset():
    for key in attr_count:
        attr_count[key] = 0
    color_stack = []

utf_chars = { "ls" : "│",
              "rs" : "│",
              "ts" : "─",
              "bs" : "─",
              "tl" : "┌",
              "tr" : "┐",
              "bl" : "└",
              "br" : "┘" }

ascii_chars = { "ls" : "|",
                "rs" : "|",
                "ts" : "-",
                "bs" : "-",
                "tl" : "+",
                "tr" : "+",
                "bl" : "+",
                "br" : "+" }

def theme_border(code):
    if "UTF-8" in locale_enc:
        return utf_chars[code]
    return ascii_chars[code]

def prep_for_display(s):
    s = s.replace("\\", "\\\\")
    s = s.replace("%", "\\%")
    s = html_entity_convert(s)
    s = char_ref_convert(s)
    return s
