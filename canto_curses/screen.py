# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from command import CommandHandler, command_format, generic_parse_error
from taglist import TagList
from input import InputBox
from reader import Reader

from threading import Thread, Event
import logging
import curses

log = logging.getLogger("SCREEN")

# The Screen class handles the layout of multiple sub-windows on the 
# main curses window. It's also the top-level gui object, so call to refresh the
# screen and get input should come through it.

class Screen(CommandHandler):
    def init(self, user_queue, callbacks, types = [TagList, InputBox]):
        self.user_queue = user_queue
        self.callbacks = callbacks
        self.layout = "default"
        self.windows = [t() for t in types]

        self.keys = {}

        self.stdscr = curses.initscr()
        if self.curses_setup() < 0:
            return -1

        self.pseudo_input_box = curses.newpad(1,1)
        self.pseudo_input_box.keypad(1)

        self.input_box = None
        self.sub_edit = False

        self.subwindows()

        # Start grabbing user input
        self.start_input_thread()

    def curses_setup(self):
        # This can throw an exception, but we shouldn't care.
        try:
            curses.curs_set(0)
        except:
            pass

        try:
            curses.cbreak()
            curses.noecho()
            curses.start_color()
            curses.use_default_colors()
        except Exception, e:
            log.error("Curses setup failed: %s" % e.msg)
            return -1

        self.height, self.width = self.stdscr.getmaxyx()

        for i, c in enumerate([ 7, 4, 3, 4, 2 ]):
            curses.init_pair(i + 1, c, -1)

        return 0

    # Translate the layout into a set of curses pads given
    # a set of coordinates relating to how they're mapped to the screen.

    def _subw_init(self, ci, top, left, width, height):
        # Height - 1 because start + height = line after bottom.

        bottom = top + (height - 1)
        right = left + (width - 1)

        refcb = lambda : self.refresh_callback(ci, top, left, bottom, right)

        # Height + 1 to account for the last curses pad line
        # not being fully writable.

        pad = curses.newpad(height + 1, width)

        # Pass on callbacks we were given from CantoCursesGui
        # plus our own.

        callbacks = self.callbacks.copy()
        callbacks["refresh"] = refcb
        callbacks["input"] = self.input_callback
        callbacks["die"] = self.die_callback

        ci.init(pad, callbacks)

    # Layout some windows into the given space, stacking with
    # orientation horizontally or vertically.

    def _subw(self, layout, top, left, height, width, orientation):
        immediates = []
        cmplx = []
        sizes = [0] * len(layout)

        # Separate windows in to two categories:
        # immediates that are defined as base classes and
        # cmplx which are lists for further processing (iterables)

        for i, unit in enumerate(layout):
            if hasattr(unit, "__iter__"):
                cmplx.append((i, unit))
            else:
                immediates.append((i,unit))

        # Units are the number of windows we'll have
        # to split the area with.

        units = len(layout)

        # Used, the amounts of space already used.
        used = 0

        for i, unit in immediates:
            # Get the size of the window from the class.
            # Each class is given, as a maximum, the largest
            # possible slice we can *guarantee*.

            if orientation == "horizontal":
                size = unit.get_width((width - used) / units)
            else:
                size = unit.get_height((height - used) / units)

            used += size

            sizes[i] = size

            # Subtract so that the next run only divides
            # the remaining space by the number of units
            # that don't have space allocated.

            units -= 1

        # All of the immediates have been allocated for.
        # So now only the cmplxs are vying for space.

        units = len(cmplx)

        for i, unit in cmplx:
            offset = sum(sizes[0:i])

            # Recursives call this function, alternating
            # the orientation, for the space we can guarantee
            # this set of windows.

            if orientation == "horizontal":
                available = (width - used) / units
                r = self._subw(unit, top, left + offset,\
                        height, available, "vertical")
                sizes[i] = max([x.pad.getmaxyx()[1] - 1 for x in r])
            else:
                available = (height - used) / units
                r = self._subw(unit, top + offset, left,\
                        available, width, "horizontal")
                sizes[i] = max([x.pad.getmaxyx()[0] - 1 for x in r])

            used += sizes[i]
            units -= 1

        # Now that we know the actual sizes (and thus locations) of
        # the windows, we actually setup the immediates.

        for i, ci in immediates:
            offset = sum(sizes[0:i])
            if orientation == "horizontal":
                self._subw_init(ci, top, left + offset,
                        sizes[i], height)
            else:
                self._subw_init(ci, top + offset, left,
                        width, sizes[i])

        return layout

    def fill_layout(self, layout, windows):
        inputs = [ w for w in windows if w.is_input() ]
        if inputs:
            self.input_box = inputs[0]
        else:
            self.input_box = None

        if layout == "hstack":
            return self.windows
        elif layout == "vstack":
            return [ self.windows ]
        else:
            if self.input_box:
                return [ [ w for w in self.windows if w != self.input_box ],\
                        self.input_box ]
            else:
                return self.windows

    def subwindows(self):
        self.stdscr.erase()
        self.stdscr.refresh()

        self.focused = None

        l = self.fill_layout(self.layout, self.windows)
        self._subw(l, 0, 0, self.height, self.width, "vertical")

        # Default to giving first window focus.
        self._focus(0)

    def refresh_callback(self, c, t, l, b, r):
        c.pad.noutrefresh(0, 0, t, l, b, r)

    def input_callback(self, prompt):
        # Setup subedit
        self.input_done.clear()
        self.input_box.edit(prompt)
        self.sub_edit = True

        # Wait for finished input
        self.input_done.wait()

        # Grab the return and reset
        r = self.input_box.result
        self.input_box.reset()
        return r

    def die_callback(self, window):
        self.windows = [ w for w in self.windows if w != window ]
        self.subwindows()
        if self.focused == window:
            self._focus(0)
        self.refresh()

    def classtype(self, args):
        t, r = self._first_term(args, lambda : self.input_callback("class: "))

        if t == "taglist":
            return (True, TagList, r)
        elif t == "reader":
            return (True, Reader, r)
        elif t == "inputbox":
            return (True, InputBox, r)

        log.error("Unknown class: %s" % t)
        return (False, None, None)

    def optint(self, args):
        if not args:
            return (True, 0, "")
        t, r = self._first_term(args, None)
        try:
            t = int(t)
        except:
            log.error("Can't parse %s as integer" % t)
            return (False, None, None)
        return (True, t, r)

    def refresh(self):
        for c in self.windows:
            c.refresh()
        curses.doupdate()

    def redraw(self):
        for c in self.windows:
            c.redraw()
        curses.doupdate()

    @command_format("resize", [])
    @generic_parse_error
    def resize(self, **kwargs):
        try:
            curses.endwin()
        except:
            pass

        # Re-enable keypad on the input box because
        # apparently endwin unsets it. Must be done
        # before the stdscr.refresh() or the first
        # keypress after KEY_RESIZE doesn't get translated
        # (you get raw bytes).

        self.pseudo_input_box.keypad(1)
        self.stdscr.refresh()

        self.curses_setup()
        self.subwindows()
        self.refresh()

    # Focus idx-th instance of cls.
    @command_format("focus", [("idx", "optint")])
    @generic_parse_error
    def focus(self, **kwargs):
        self._focus(kwargs["idx"])

    def _focus(self, idx):
        l = len(self.windows)
        if -1 * l < idx < l:
            self.focused = self.windows[idx]
            log.debug("Focusing window %d (%s)" % (idx, self.focused))
        else:
            log.debug("Couldn't find window %d" % idx)

    def _window_levels(self, toplevel):
        for i in reversed(toplevel):
            if hasattr(i, "__iter__"):
                return [self] + [ self._window_levels(i) ]
        return toplevel

    @command_format("add-window", [("cls","classtype")])
    @generic_parse_error
    def add_window(self, **kwargs):
        self._add_window(kwargs["cls"])

    def _add_window(self, cls):
        self.windows.append(cls())
        self.subwindows()
        self._focus(-1)
        self.refresh()

    # Pass a command to focused window:

    def command(self, cmd):
        if cmd.startswith("focus"):
            self.focus(args=cmd)
        elif cmd.startswith("resize"):
            self.resize(args=cmd)
        elif cmd.startswith("add-window"):
            self.add_window(args=cmd)

        # Propagate command to focused window
        else:
            self.focused.command(cmd)

    def key(self, k):
        r = CommandHandler.key(self, k)
        if r:
            return r
        if self.focused:
            return self.focused.key(k)
        return None

    def input_thread(self):
        while True:
            r = self.pseudo_input_box.getch()

            log.debug("R = %s" % r)

            # We're in an edit box
            if self.sub_edit:
                # Feed the key to the input_box
                rc = self.input_box.addkey(r)

                # If rc == 1, need more keys
                # If rc == 0, all done (result could still be "" though)
                if not rc:
                    self.sub_edit = False
                    self.input_done.set()
                    self.callbacks["set_var"]("needs_redraw", True)
                continue

            # We're not in an edit box.

            # Convert to a writable character, if in the ASCII range
            if r < 256:
                r = chr(r)

            self.user_queue.put(("KEY", r))

    def start_input_thread(self):
        self.input_done = Event()
        self.inthread =\
                Thread(target = self.input_thread)

        self.inthread.daemon = True
        self.inthread.start()

    def exit(self):
        curses.endwin()


