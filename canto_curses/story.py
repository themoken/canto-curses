# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import Plugin, PluginHandler
from canto_next.hooks import on_hook, remove_hook

from theme import FakePad, WrapPad, theme_print, theme_len, theme_process
from parser import parse_conditionals, eval_theme_string

import traceback
import logging
import curses

log = logging.getLogger("STORY")

class StoryPlugin(Plugin):
    pass

# The Story class is the basic wrapper for an item to be displayed. It manages
# its own state only because it affects its representation, it's up to a higher
# class to actually communicate state changes to the backend.

DEFAULT_FSTRING = "%?{en}([%i] :)%?{ren}([%x] :)%?{sel}(%R:)%?{rd}(%3:%2%B)%t%0%?{rd}(:%b)%?{sel}(%r:)"

class Story(PluginHandler):
    def __init__(self, id, callbacks):
        PluginHandler.__init__(self)
        self.plugin_class = StoryPlugin
        self.callbacks = callbacks
        self.content = {}
        self.id = id
        self.selected = False

        # Retain arguments from last refresh call.
        self.width = 0

        self.offset = 0
        self.rel_offset = 0

        # Lines used in last successful render
        self.lines = 0

        self.pad = None

        # Status of hooks
        self.att_queued = False

        on_hook("opt_change", self.on_opt_change)
        on_hook("tag_opt_change", self.on_tag_opt_change)

    def die(self):
        remove_hook("opt_change", self.on_opt_change)
        remove_hook("tag_opt_change", self.on_tag_opt_change)

    def __eq__(self, other):
        if not other:
            return False
        if not hasattr(other, "id"):
            return False
        return self.id == other.id

    def on_attributes(self, attributes):
        if self in attributes:
            remove_hook("attributes", self.on_attributes)
            self.att_queued = False

            # Don't bother checking attributes. If we're still
            # lacking, refresh_self will re-enable this hook

            self.callbacks["set_var"]("needs_refresh", True)
            self.refresh_self()

    def on_opt_change(self, config):
        if "story.enumerated" in config:
            self.refresh_self()

    def on_tag_opt_change(self, tag, config):
        if self in tag and "enumerated" in config:
            self.refresh_self()

    # Simple hook wrapper to make sure we don't have multiple
    # on_attribute hooks registered.

    def queue_need_attributes(self):
        if not self.att_queued:
            on_hook("attributes", self.on_attributes)
            self.att_queued = True

    # Add / remove state. Return True if an actual change, False otherwise.

    def handle_state(self, attr):
        if self.content["canto-state"] == "":
            self.content["canto-state"] = []

        # Negative attribute
        if attr[0] == "-":
            attr = attr[1:]
            if attr in self.content["canto-state"]:
                self.content["canto-state"].remove(attr)
                self.refresh_self()
                return True

        # Positive attribute
        elif attr not in self.content["canto-state"]:
            self.content["canto-state"].append(attr)
            self.refresh_self()
            return True

        return False

    def select(self):
        if not self.selected:
            self.selected = True
            self.refresh_self()

    def unselect(self):
        if self.selected:
            self.selected = False
            self.refresh_self()

    def set_offset(self, offset):
        if self.offset != offset:
            self.offset = offset
            self.refresh_self()

    def set_rel_offset(self, offset):
        if self.rel_offset != offset:
            self.rel_offset = offset
            self.refresh_self()

    def refresh_self(self):
        self.refresh(self.width)

    def refresh(self, width):
        # The pad isn't init'd, ignore.
        if width == 0:
            return

        # Record arguments for subsequent internal calls.
        self.width = width

        # Make sure we actually have all of the attributes needed
        # to complete the render.

        for attr in self.needed_attributes():
            if attr not in self.content:
                self.pad = curses.newpad(1, width)
                self.pad.addstr("Waiting on content...")
                self.lines = 1

                # Sign up for notification
                self.queue_need_attributes()
                return

        # Do we need the enumerated form?
        enumerated = self.callbacks["get_opt"]("story.enumerated")

        # Do we need the relative enumerated form?
        rel_enumerated = self.callbacks["get_tag_opt"]("enumerated")

        # Get format string
        fstring = self.callbacks["get_opt"]("story.format")

        # These are the only things that affect the drawing
        # of this item.

        state = { "width" : width,
                  "abs_idx" : self.offset,
                  "rel_idx" : self.rel_offset,
                  "rel_enumerated" : rel_enumerated,
                  "enumerated" : enumerated,
                  "state" : self.content["canto-state"][:],
                  "selected" : self.selected,
                  "fstring" : fstring }

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
        lines = self.render(FakePad(width), unenum_state)

        # Create the new pad and actually do the render.

        self.pad = curses.newpad(lines, width)
        self.render(WrapPad(self.pad), state)

        # If we use up more / fewer lines than last time, we need
        # to refresh to remap the items.

        if lines != self.lines:
            self.callbacks["set_var"]("needs_refresh", True)
            self.lines = lines
        self.callbacks["set_var"]("needs_redraw", True)

    def render(self, pad, state):

        try:
            parsed = parse_conditionals(state["fstring"])
        except Exception, e:
            log.warn("Failed to parse conditionals in fstring: %s" % state["fstring"])
            log.warn("\n" + "".join(traceback.format_exc(e)))
            log.warn("Falling back to default.")
            parsed = parse_conditionals(DEFAULT_FSTRING)

        # These are escapes that are handled in the theme_print
        # lower in the function and should remain present after
        # evaluation.

        passthru = {}
        for c in "RrDdUuBbSs012345678":
            passthru[c] = "%" + c

        values = { 'en' : state["enumerated"],
                    'i' : state["abs_idx"],
                  'ren' : state["rel_enumerated"],
                    'x' : state["rel_idx"],
                  'sel' : self.selected,
                   'rd' : "read" in self.content["canto-state"],
                    't' : self.content["title"],
                    'l' : self.content["link"],
                 'item' : self }

        values.update(passthru)

        try:
            s = eval_theme_string(parsed, values)
        except Exception, e:
            log.warn("Failed to evaluate fstring: %s" % state["fstring"])
            log.warn("\n" + "".join(traceback.format_exc(e)))
            log.warn("Falling back to default")

            parsed = parse_conditional(DEFAULT_STRING)
            s = eval_theme_string(parsed, values)

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

                s = theme_print(pad, s, state["width"], l, right)

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
