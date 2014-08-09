# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2014 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import Plugin, PluginHandler
from canto_next.hooks import on_hook, remove_hook

from .theme import FakePad, WrapPad, theme_print, theme_len, theme_process, theme_reset, theme_border
from .parser import parse_conditionals, eval_theme_string, prep_for_display
from .config import DEFAULT_FSTRING
from .tagcore import tag_updater

import traceback
import logging
import curses

log = logging.getLogger("STORY")

class StoryPlugin(Plugin):
    pass

# The Story class is the basic wrapper for an item to be displayed. It manages
# its own state only because it affects its representation, it's up to a higher
# class to actually communicate state changes to the backend.


class Story(PluginHandler):
    def __init__(self, tag, id, callbacks):
        PluginHandler.__init__(self)

        self.callbacks = callbacks

        self.parent_tag = tag
        self.id = id
        self.pad = None

        self.selected = False
        self.marked = False

        # Are there changes pending?
        self.changed = True

        self.fresh_state = False
        self.fresh_tags = False

        # Information from last refresh
        self.width = 0
        self.lines = 0

        # Pre and post formats, to be used by plugins
        self.pre_format = ""
        self.post_format = ""

        # Lines not in our pad, but placed after us (tag footer)

        self.extra_lines = 0

        # Offset globally and in-tag.
        self.offset = 0
        self.rel_offset = 0

        # This should exist before the hook is setup, or the hook will fail.
        self.content = {}

        on_hook("curses_opt_change", self.on_opt_change)
        on_hook("curses_tag_opt_change", self.on_tag_opt_change)
        on_hook("curses_attributes", self.on_attributes)

        # Grab initial content, if any, the rest will be handled by the
        # attributes hook

        self.content = tag_updater.get_attributes(self.id)
        self.new_content = None

        self.plugin_class = StoryPlugin
        self.update_plugin_lookups()

    def die(self):
        self.parent_tag = None
        remove_hook("curses_opt_change", self.on_opt_change)
        remove_hook("curses_tag_opt_change", self.on_tag_opt_change)
        remove_hook("curses_attributes", self.on_attributes)

    def __eq__(self, other):
        if not other:
            return False
        if not hasattr(other, "id"):
            return False
        return self.id == other.id

    def __str__(self):
        return "story: %s" % self.id

    # On_attributes updates new_content. We don't lock because we don't
    # particularly care what version of new_content the next sync() call gets.

    def on_attributes(self, attributes):
        if self.id in attributes:
            new_content = attributes[self.id]

            if not (new_content is self.content):
                self.new_content = new_content

    def sync(self):
        if self.new_content == None:
            return

        old_content = self.content
        self.content = self.new_content
        self.new_content = None

        if 'canto-state' in old_content and self.fresh_state:
            self.content['canto-state'] = old_content['canto-state']
            self.fresh_state = False

        if 'canto-tags' in old_content and self.fresh_tags:
            self.content['canto-tags'] = old_content['canto-tags']
            self.fresh_tags = False

        self.need_redraw()

    def on_opt_change(self, config):
        if "taglist" in config and "border" in config["taglist"]:
            self.need_redraw()

        if "story" not in config:
            return

        if "format_attrs" in config["story"]:
            needed_attrs = []
            for attr in config["story"]["format_attrs"]:
                if attr not in self.content:
                    needed_attrs.append(attr)
            if needed_attrs:
                log.debug("%s needs: %s" % (self.id, needed_attrs))
                tag_updater.need_attributes(self.id, needed_attrs)

        # All other story options are formats / enumerations, redraw.

        self.need_redraw()

    def on_tag_opt_change(self, config):
        tagname = self.callbacks["get_tag_name"]()
        if tagname in config and "enumerated" in config[tagname]:
            self.need_redraw()

    # Add / remove state. Return True if an actual change, False otherwise.

    def _handle_key(self, attr, key):
        if key not in self.content or self.content[key] == "":
            self.content[key] = []

        # Negative attribute
        if attr[0] == "-":
            attr = attr[1:]
            if attr == "marked":
                return self.unmark()
            elif attr in self.content[key]:
                self.content[key].remove(attr)
                self.need_redraw()
                return True

        # Positive attribute
        else:
            if attr == "marked":
                return self.mark()
            elif attr not in self.content[key]:
                self.content[key].append(attr)
                self.need_redraw()
                return True
        return False

    # Simple wrapper to call tag's item_state_change callback on an actual
    # change.

    def handle_state(self, attr):
        r = self._handle_key(attr, "canto-state")
        if r:
            self.fresh_state = True
            self.callbacks["item_state_change"](self)
        return r

    def handle_tag(self, tag):
        r = self._handle_key(tag, "canto-tags")
        if r:
            self.fresh_tags = True
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
                log.debug("%s still needs %s" % (self, attr))
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
                  "user_tags" : self.content["canto-tags"][:],
                  "selected" : self.selected,
                  "marked" : self.marked,
                  "pre" : self.pre_format,
                  "post" : self.post_format,
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
            log.warn("\n" + "".join(traceback.format_exc()))
            log.warn("Falling back to default.")
            parsed = parse_conditionals(DEFAULT_FSTRING)

        # These are escapes that are handled in the theme_print
        # lower in the function and should remain present after
        # evaluation.

        passthru = {}
        for c in "RrDdUuBbSs012345678[":
            passthru[c] = "%" + c

        # Add refactored themability variables:

        story_conf = self.callbacks["get_opt"]("story")
        for attr in [ "selected", "read", "marked" ]:
            passthru[attr] = story_conf[attr]
            passthru["un" + attr] = story_conf["un" + attr]
            passthru[attr + "_end"] = story_conf[attr + "_end"]
            passthru["un" + attr + "_end"] = story_conf["un" + attr + "_end"]

        values = { 'en' : state["enumerated"],
                    'i' : state["abs_idx"],
                  'ren' : state["rel_enumerated"],
                    'x' : state["rel_idx"],
                  'sel' : state["selected"],
                    'm' : state["marked"],
                  'pre' : state["pre"],
                 'post' : state["post"],
                   'rd' : "read" in state["state"],
                   'ut' : state["user_tags"],
                    't' : self.content["title"],
                    'l' : self.content["link"],
                 'item' : self,
                 'prep' : prep_for_display}

        # Prep all text values for display.

        for value in list(values.keys()):
            if type(values[value]) == str:
                values[value] = prep_for_display(values[value])

        values.update(passthru)

        try:
            s = eval_theme_string(parsed, values)
        except Exception as e:
            log.warn("Failed to evaluate fstring: %s" % state["fstring"])
            log.warn("\n" + "".join(traceback.format_exc()))
            log.warn("Falling back to default")

            parsed = parse_conditionals(DEFAULT_FSTRING)
            s = eval_theme_string(parsed, values)

        # s is now a themed line based on this story.
        # This doesn't include a border.

        lines = 0

        taglist_conf = self.callbacks["get_opt"]("taglist")

        if taglist_conf["border"]:
            left = "%C%B%1" + theme_border("ls") + "%0%b %c"
            left_more = "%C%B%1" + theme_border("ls") + "%0%b     %c"
            right = "%C %B%1" + theme_border("rs") + "%0%b%c"
        else:
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
                        try:
                            pad.waddch(".")
                        except:
                            # We have to encode this as UTF-8 because of python
                            # bug 12567, fixed in 3.3

                            pad.waddch(".".encode("UTF-8"))

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
            tb = traceback.format_exc()
            log.debug("Story exception:")
            log.debug("\n" + "".join(tb))

        # Reset theme counters
        theme_reset()

        # Return number of lines this story took to render entirely.
        return lines
