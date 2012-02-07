# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import Plugin, PluginHandler
from canto_next.hooks import on_hook, remove_hook

from .theme import FakePad, WrapPad, theme_print, theme_len, theme_process
from .parser import parse_conditionals, eval_theme_string, prep_for_display

import traceback
import logging
import curses

log = logging.getLogger("STORY")

class StoryPlugin(Plugin):
    pass

# The Story class is the basic wrapper for an item to be displayed. It manages
# its own state only because it affects its representation, it's up to a higher
# class to actually communicate state changes to the backend.

DEFAULT_FSTRING = "%1%?{en}([%i] :)%?{ren}([%x] :)%?{sel}(%R:)%?{rd}(%3:%2%B)%?{m}(*%8%B:)%t%?{m}(%b%0:)%?{rd}(%0:%b%0)%?{sel}(%r:)%0"

class Story(PluginHandler):
    def __init__(self, id, callbacks):
        PluginHandler.__init__(self)

        self.plugin_class = StoryPlugin
        self.update_plugin_lookups()

        self.callbacks = callbacks
        self.content = {}
        self.id = id
        self.pad = None

        self.selected = False
        self.marked = False

        # Are there changes pending?
        self.changed = True

        # Information from last refresh
        self.width = 0
        self.lines = 0

        # Offset globally and in-tag.
        self.offset = 0
        self.rel_offset = 0

        on_hook("opt_change", self.on_opt_change)
        on_hook("tag_opt_change", self.on_tag_opt_change)
        on_hook("attributes", self.on_attributes)

    def die(self):
        remove_hook("opt_change", self.on_opt_change)
        remove_hook("tag_opt_change", self.on_tag_opt_change)
        remove_hook("attributes", self.on_attributes)

    def __eq__(self, other):
        if not other:
            return False
        if not hasattr(other, "id"):
            return False
        return self.id == other.id

    def on_attributes(self, attributes):
        if self.id in attributes:
            # Don't bother checking attributes. If we're still
            # lacking, need_redraw will re-enable this hook

            self.need_redraw()

    def on_opt_change(self, config):
        if "story" not in config:
            return

        if "format_attrs" in config["story"]:
            needed_attrs = []
            for attr in config["story"]["format_attrs"]:
                if attr not in self.content:
                    needed_attrs.append(attr)
            if needed_attrs:
                log.debug("%s needs: %s" % (self.id, needed_attrs))
                self.callbacks["write"]("ATTRIBUTES",\
                        { self.id : needed_attrs })

        if "enumerated" in config["story"] or "format" in config["story"]:
            self.need_redraw()

    def on_tag_opt_change(self, config):
        tagname = self.callbacks["get_tag_name"]()
        if tagname in config and "enumerated" in config[tagname]:
            self.need_redraw()

    # Add / remove state. Return True if an actual change, False otherwise.

    def _handle_state(self, attr):
        if self.content["canto-state"] == "":
            self.content["canto-state"] = []

        # Negative attribute
        if attr[0] == "-":
            attr = attr[1:]
            if attr == "marked":
                return self.unmark()
            elif attr in self.content["canto-state"]:
                self.content["canto-state"].remove(attr)
                self.need_redraw()
                return True

        # Positive attribute
        else:
            if attr == "marked":
                return self.mark()
            elif attr not in self.content["canto-state"]:
                self.content["canto-state"].append(attr)
                self.need_redraw()
                return True
        return False

    # Simple wrapper to call tag's item_state_change callback on an actual
    # change.

    def handle_state(self, attr):
        r = self._handle_state(attr)
        if r:
            self.callbacks["item_state_change"](self)
        return r

    def select(self):
        if not self.selected:
            self.selected = True
            self.need_redraw()

    def unselect(self):
        if self.selected:
            self.selected = False
            self.need_redraw()

    def mark(self):
        if not self.marked:
            self.marked = True
            self.need_redraw()
            return True
        return False

    def unmark(self):
        if self.marked:
            self.marked = False
            self.need_redraw()
            return True
        return False

    def set_offset(self, offset):
        if self.offset != offset:
            self.offset = offset
            self.need_redraw()

    def set_rel_offset(self, offset):
        if self.rel_offset != offset:
            self.rel_offset = offset
            self.need_redraw()

    # This is not useful in the interface,
    # so no redraw required on it.

    def set_sel_offset(self, offset):
        self.sel_offset = offset

    def need_redraw(self):
        self.changed = True
        self.callbacks["set_var"]("needs_redraw", True)

    def do_changes(self, width):
        if width != self.width or self.changed:
            self.refresh(width)

    def refresh(self, width):
        story_conf = self.callbacks["get_opt"]("story")
        self.width = width

        # Make sure we actually have all of the attributes needed
        # to complete the render.

        for attr in story_conf["format_attrs"]:
            if attr not in self.content:
                self.pad = curses.newpad(1, width)
                self.pad.addstr("Waiting on content...")
                self.lines = 1
                return

        # Do we need the relative enumerated form?
        rel_enumerated = self.callbacks["get_tag_opt"]("enumerated")

        # These are the only things that affect the drawing
        # of this item.

        state = { "width" : width,
                  "abs_idx" : self.offset,
                  "rel_idx" : self.rel_offset,
                  "rel_enumerated" : rel_enumerated,
                  "enumerated" : story_conf["enumerated"],
                  "state" : self.content["canto-state"][:],
                  "selected" : self.selected,
                  "marked" : self.marked,
                  "fstring" : story_conf["format"] }

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

        self.lines = lines
        self.changed = False

    def render(self, pad, state):

        try:
            parsed = parse_conditionals(state["fstring"])
        except Exception as e:
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
                  'sel' : state["selected"],
                    'm' : state["marked"],
                   'rd' : "read" in self.content["canto-state"],
                    't' : self.content["title"],
                    'l' : self.content["link"],
                 'item' : self,
                 'prep' : prep_for_display}

        # Prep all text values for display.

        for value in list(values.keys()):
            if type(values[value]) in [str, str]:
                values[value] = prep_for_display(values[value])

        values.update(passthru)

        try:
            s = eval_theme_string(parsed, values)
        except Exception as e:
            log.warn("Failed to evaluate fstring: %s" % state["fstring"])
            log.warn("\n" + "".join(traceback.format_exc(e)))
            log.warn("Falling back to default")

            parsed = parse_conditionals(DEFAULT_FSTRING)
            s = eval_theme_string(parsed, values)

        # s is now a themed line based on this story.
        # This doesn't include a border.

        lines = 0

        left = "%C %c"
        left_more = "%C     %c"
        right = "%C %c"

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
                    for i in range(3):
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

        except Exception as e:
            log.debug("Story exception: %s" % (e,))

        # Return number of lines this story took to render entirely.
        return lines
