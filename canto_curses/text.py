# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2016 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.hooks import on_hook, unhook_all

from .theme import FakePad, WrapPad, theme_print, theme_lstrip, theme_border, theme_reset
from .command import register_commands, unregister_command
from .guibase import GuiBase
from .color import cc

import logging
import curses

log = logging.getLogger("TEXTBOX")

class TextBox(GuiBase):
    def init(self, pad, callbacks, lstrip=True):
        GuiBase.init(self)

        self.pad = pad

        self.max_offset = 0

        self.callbacks = callbacks

        self.lstrip = lstrip
        self.text = ""

        # This relies on the actual subclasses (i.e. Reader) to cleanup.

        cmds = { "page-down" : (self.cmd_page_down, [], "Next page of text"),
                "page-up" : (self.cmd_page_up, [], "Previous page of text"),
                "scroll-up" : (self.cmd_scroll_up, [], "Scroll up"),
                "scroll-down" : (self.cmd_scroll_down, [], "Scroll down"),
        }

        register_commands(self, cmds)

    def get_offset(self):
        return self.callbacks["get_var"](self.get_opt_name() + "_offset")

    def set_offset(self, offset):
        self.callbacks["set_var"](self.get_opt_name() + "_offset", offset)

    def update_text(self):
        pass

    def refresh(self):
        self.height, self.width = self.pad.getmaxyx()

        fp = FakePad(self.width)
        lines = self.render(fp)

        # Create pre-rendered pad
        self.fullpad = curses.newpad(lines, self.width)
        self.render(WrapPad(self.fullpad))

        # Update offset based on new display properties.
        self.max_offset = max((lines - 1) - (self.height - 1), 0)

        offset = min(self.get_offset(), self.max_offset)
        self.set_offset(offset)
        self.callbacks["set_var"]("needs_redraw", True)

    def redraw(self):
        offset = self.get_offset()
        tb, lb, bb, rb = self.callbacks["border"]()

        # Overwrite visible pad with relevant area of pre-rendered pad.
        self.pad.erase()

        realheight = min(self.height, self.fullpad.getmaxyx()[0]) - 1

        top = 0
        if tb:
            self.pad.move(0, 0)
            self.render_top_border(WrapPad(self.pad))
            top += 1

        self.fullpad.overwrite(self.pad, offset, 0, top, 0,\
                realheight - top, self.width - 1)

        if bb:
            # If we're not floating, then the bottom border
            # belongs at the bottom of the given window.

            if not self.callbacks["floating"]():
                padheight = self.pad.getmaxyx()[0] -1
                self.pad.move(padheight - 1, 0)
                self.render_bottom_border(WrapPad(self.pad))
                self.pad.move(padheight - 1, 0)
            else:
                self.pad.move(realheight - 1, 0)
                self.render_bottom_border(WrapPad(self.pad))
                self.pad.move(realheight - 1, 0)
        else:
            self.pad.move(realheight - 1, 0)

        self.callbacks["refresh"]()

    def render_top_border(self, pad):
        tb, lb, bb, rb = self.callbacks["border"]()

        lc = " "
        if lb:
            lc = "%C" + theme_border("tl") + "%c"

        rc = " "
        if rb:
            rc = "%C" + theme_border("tr") + "%c"

        mainbar = "%C" + (theme_border("ts") * (self.width - 1)) + "%c"
        theme_print(pad, mainbar, self.width, lc, rc)

    def render_bottom_border(self, pad):
        tb, lb, bb, rb = self.callbacks["border"]()

        lc = " "
        if lb:
            lc = "%C" + theme_border("bl") + "%c"

        rc = " "
        if rb:
            rc = "%C" + theme_border("br") + "%c"

        mainbar = "%C" + (theme_border("ts") * (self.width - 1)) + "%c"
        theme_print(pad, mainbar, self.width, lc, rc)

    def render(self, pad):
        self.update_text()

        tb, lb, bb, rb = self.callbacks["border"]()
        s = self.text

        lines = 0

        # Account for potential top border rendered on redraw.
        if tb:
            lines += 1

        # Prepare left and right borders

        l = " "
        if lb:
            l = "%C" + theme_border("ls") + " %c"
        r = " "
        if rb:
            r = "%C " + theme_border("rs") + "%c"

        # Render main content

        while s:
            if self.lstrip:
                s = theme_lstrip(pad, s)
            if s:
                s = theme_print(pad, s, self.width, l, r)
                lines += 1

        # Account for potential bottom rendered on redraw.
        if bb:
            lines += 1

        theme_reset()

        # Return one extra line because the rest of the reader
        # code knows to avoid the dead cell on the bottom right
        # of every curses pad.

        return lines + 1

    def cmd_scroll_up(self):
        self._relscroll(-1)

    def cmd_scroll_down(self):
        self._relscroll(1)

    def cmd_page_up(self):
        self._relscroll(-1 * (self.height - 1))

    def cmd_page_down(self):
        self._relscroll(self.height - 1)

    def _relscroll(self, factor):
        offset = self.get_offset()
        offset += factor
        offset = min(offset, self.max_offset)
        offset = max(offset, 0)

        self.set_offset(offset)
        self.callbacks["set_var"]("needs_redraw", True)

    def is_input(self):
        return False

    def get_opt_name(self):
        return "textbox"

    def get_height(self, mheight):
        return mheight

    def get_width(self, mwidth):
        return mwidth

class VarBox(TextBox):
    def init(self, pad, callbacks, var):
        TextBox.init(self, pad, callbacks, False)
        unregister_command(self, "bind")
        self.var = var
        self.value = self.callbacks["get_var"](var)

        on_hook("curses_var_change", self.on_var_change, self)

    def on_var_change(self, change):
        if self.var in change:
            self.value = change[self.var]
            if self.value == "":
                self.cmd_destroy()
            self.callbacks["set_var"]("needs_refresh", True)

    def cmd_destroy(self):
        unhook_all(self)
        TextBox.cmd_destroy(self)

class InfoBox(VarBox):
    def init(self, pad, callbacks):
        VarBox.init(self, pad, callbacks, "info_msg")

    def update_text(self):
        self.text = self.value

    def get_opt_name(self):
        return "infobox"

class ErrorBox(VarBox):
    def init(self, pad, callbacks):
        VarBox.init(self, pad, callbacks, "error_msg")

    def update_text(self):
        self.text = cc("error") + self.value + "%0"

    def get_opt_name(self):
        return "errorbox"
