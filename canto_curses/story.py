# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from theme import FakePad, WrapPad, theme_print, theme_len, theme_process

import logging
import curses

log = logging.getLogger("STORY")

# The Story class is the basic wrapper for an item to be displayed. It manages
# its own state only because it affects its representation, it's up to a higher
# class to actually communicate state changes to the backend.

class Story():
    def __init__(self, id, callbacks):
        self.callbacks = callbacks
        self.content = {}
        self.id = id
        self.selected = False
        self.cached_state = {}

    def __eq__(self, other):
        if not other:
            return False
        return self.id == other.id

    # Add / remove state. Return True if an actual change, False otherwise.

    def handle_state(self, attr):
        if self.content["canto-state"] == "":
            self.content["canto-state"] = []

        # Negative attribute
        if attr[0] == "-":
            attr = attr[1:]
            if attr in self.content["canto-state"]:
                self.content["canto-state"].remove(attr)
                return True

        # Positive attribute
        elif attr not in self.content["canto-state"]:
            self.content["canto-state"].append(attr)
            return True

        return False

    def select(self):
        self.selected = True

    def unselect(self):
        self.selected = False

    def refresh(self, mwidth, tag_offset, rel_idx):

        # Make sure we actually have all of the attributes needed
        # to complete the render.

        for attr in self.needed_attributes():
            if attr not in self.content:
                self.pad = curses.newpad(1, mwidth)
                self.pad.addstr("Waiting on content...")
                self.callbacks["set_var"]("needs_deferred_refresh", True)
                return 1

        # Do we need the enumerated form?
        enumerated = self.callbacks["get_opt"]("story.enumerated")

        # Do we need the relative enumerated form?
        rel_enumerated = self.callbacks["get_tag_opt"]("enumerated")

        # These are the only things that affect the drawing
        # of this item.

        state = { "mwidth" : mwidth,
                  "abs_idx" : tag_offset + rel_idx,
                  "rel_idx" : rel_idx,
                  "rel_enumerated" : rel_enumerated,
                  "enumerated" : enumerated,
                  "state" : self.content["canto-state"][:],
                  "selected" : self.selected }

        # If the last refresh call had the same parameters and
        # settings, then we don't need to touch the actual pad.

        if self.cached_state == state:
            return self.pad.getmaxyx()[0]

        self.cached_state = state

        # Render once to a FakePad (no IO) to determine the correct
        # amount of lines. Force this to entirely unenumerated because
        # we don't want the enumerated content to take any more lines
        # than the unenumerated. Render will truncate smartly if we
        # attempt to go over. This avoids insane amounts of line shifting
        # when enumerating items and allows us to get the perfect size
        # for this story's pad.

        unenum_state = state.copy()
        unenum_state["enumerated"] = False
        unenum_state["rel_enumerated"] = False
        lines = self.render(FakePad(mwidth), unenum_state)

        # Create the new pad and actually do the render.

        self.pad = curses.newpad(lines, mwidth)
        return self.render(WrapPad(self.pad), state)

    def render(self, pad, state):

        # The first render step is to get a big long line
        # describing what we want to render with the
        # given state.

        pre = ""
        post = ""

        if self.selected:
            pre = "%R" + pre
            post = post + "%r"

        if "read" in self.content["canto-state"]:
            pre = pre + "%3"
            post = "%0" + post
        else:
            pre = pre + "%2%B"
            post = "%b%0" + post

        # Just like with tags, stories can be both absolute and relatively
        # enumerated at the same time and the absolute enumeration has to
        # come first, so it prepended last.

        if state["rel_enumerated"]:
            pre = ("[%d] " % state["rel_idx"]) + pre

        if state["enumerated"]:
            pre = ("[%d] " % state["abs_idx"]) + pre

        s = pre + self.content["title"] + post

        # s is now a themed line based on this story.
        # This doesn't include a border.

        lines = 0

        left = u"%C %c"
        left_more = u"%C     %c"
        right = u"%C %c"

        try:
            while s:
                # Left border, for first line
                if lines == 0:
                    l = left

                # Left border, for subsequent lines (indent)
                else:
                    l = left_more

                s = theme_print(pad, s, state["mwidth"], l, right)

                # Avoid line shifting when temporarily enumerating.
                if s and (state["enumerated"] or state["rel_enumerated"]) and\
                        lines == (self.unenumerated_lines - 1):
                    pad.move(pad.getyx()[0],\
                            pad.getyx()[1] - (theme_len(right) + 3))

                    # Write out the ellipsis.
                    for i in xrange(3):
                        pad.waddch('.')

                    # Handling any dangling codes
                    theme_process(pad, s)
                    s = None

                # Keep track of lines for this item
                lines += 1

            # Keep track of unenumerated lines so that we can
            # do the above shift-avoiding.

            if not state["enumerated"] and not state["rel_enumerated"]:
                self.unenumerated_lines = lines

        # Render exceptions should be non-fatal. The worst
        # case scenario is that one story's worth of space
        # is going to be fucked up.

        except Exception, e:
            log.debug("Story exception: %s" % (e,))

        # Return number of lines this story took to render entirely.
        return lines

    # Return what attributes of this story are needed
    # to render it. Eventually this will be determined
    # on the client render string.

    def needed_attributes(self):
        return [ "title", "link", "canto-state" ]
