# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2016 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import Plugin, PluginHandler
from canto_next.hooks import on_hook, unhook_all

from .theme import FakePad, WrapPad, theme_print, theme_len, theme_reset, theme_border, prep_for_display
from .tagcore import tag_updater
from .config import story_needed_attrs
from .color import cc

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
        self.is_tag = False
        self.is_dead = False
        self.id = id
        self.pad = None

        self.selected = False
        self.marked = False

        # Are there changes pending?
        self.changed = True

        self.fresh_state = False
        self.fresh_tags = False

        self.width = 0

        # This is used by the rendering code.
        self.extra_lines = 0

        # Pre and post formats, to be used by plugins
        self.pre_format = ""
        self.post_format = ""

        # Offset globally and in-tag.
        self.offset = 0
        self.rel_offset = 0
        self.enumerated = False
        self.rel_enumerated = False

        # This should exist before the hook is setup, or the hook will fail.
        self.content = {}

        on_hook("curses_opt_change", self.on_opt_change, self)
        on_hook("curses_tag_opt_change", self.on_tag_opt_change, self)
        on_hook("curses_attributes", self.on_attributes, self)

        # Grab initial content, if any, the rest will be handled by the
        # attributes hook

        self.content = tag_updater.get_attributes(self.id)
        self.new_content = None

        self.plugin_class = StoryPlugin
        self.update_plugin_lookups()

    def die(self):
        self.is_dead = True
        unhook_all(self)

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
        if "taglist" in config and ("border" in config["taglist"] or "wrap" in config["taglist"]):
            self.need_redraw()

        if "color" in config or "style" in config:
            self.need_redraw()

        if "story" not in config:
            return

        if "format_attrs" in config["story"]:
            needed_attrs = []
            for attr in config["story"]["format_attrs"]:
                if attr not in self.content:
                    needed_attrs.append(attr)
            if needed_attrs:
                log.debug("%s needs: %s", self.id, needed_attrs)
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

        # Toggle attribute
        elif attr[0] == '%':
            attr = attr[1:]
            if attr == "marked":
                if self.marked:
                    self.unmark()
                else:
                    self.mark()
            else:
                if attr in self.content[key]:
                    self.content[key].remove(attr)
                else:
                    self.content[key].append(attr)
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

    def need_refresh(self):
        self.changed = True
        self.callbacks["set_var"]("needs_refresh", True)

    def eval(self):
        s = ""

        if "read" in self.content["canto-state"]:
            s += cc("read")
        else:
            s += cc("unread")

        if self.marked:
            s += cc("marked") + "[*]"

        if self.selected:
            s += cc("selected")

        s += prep_for_display(self.content["title"])

        if self.selected:
            s += cc.end("selected")

        if self.marked:
            s += cc.end("marked")

        if "read" in self.content["canto-state"]:
            s += cc.end("read")
        else:
            s += cc.end("unread")

        return s

    def lines(self, width):
        if width == self.width and not self.changed:
            return self.lns + self.extra_lines

        # Make sure we actually have all of the attributes needed
        # to complete the render.

        self.enumerated = self.callbacks["get_opt"]("story.enumerated")
        self.rel_enumerated = self.callbacks["get_tag_opt"]("enumerated")

        for attr in story_needed_attrs:
            if attr not in self.content:

                # Not having needed info is a good reason to
                # sync.

                self.sync()
                self.need_refresh()
                self.callbacks["release_gui"]()

                log.debug("%s still needs %s", self, attr)

                self.left = " "
                self.left_more = " "
                self.right = " "

                self.evald_string = "Waiting on content..."

                self.lns = 1
                return self.lns

        for attr in list(self.plugin_attrs.keys()):
            if not attr.startswith("edit_"):
                continue
            try:
                getattr(self, attr)()
            except:
                log.error("Error running story editing plugin")
                log.error(traceback.format_exc())

        self.evald_string = self.eval()

        taglist_conf = self.callbacks["get_opt"]("taglist")

        if taglist_conf["border"]:
            self.left = "%C%B" + theme_border("ls") + "%b %c"
            self.left_more = "%C%B" + theme_border("ls") + "%b     %c"
            self.right = "%C %B" + theme_border("rs") + "%b%c"
        else:
            self.left = "%C %c"
            self.left_more = "%C     %c"
            self.right = "%C %c"

        self.pad = None
        self.width = width
        self.changed = False

        self.lns = self.render(FakePad(width), width)
        if (not taglist_conf["wrap"]) and self.lns:
            self.lns = 1

        return self.lns

    def pads(self, width):
        if self.pad and not self.changed:
            return self.lns

        self.pad = curses.newpad(self.lines(width), width)
        self.render(WrapPad(self.pad), width)
        return self.lns

    def render(self, pad, width):
        s = self.evald_string

        lines = 0

        try:
            while s:
                # Left border, for first line
                if lines == 0:
                    l = self.left

                # Left border, for subsequent lines (indent)
                else:
                    l = self.left_more

                s = theme_print(pad, s, width, l, self.right)

                # Handle overwriting with offset information

                if lines == 0:
                    header = ""
                    if self.enumerated:
                        header += cc("enum_hints") + "[" + str(self.offset) + "]%0"
                    if self.rel_enumerated:
                        header += cc("enum_hints") + "[" + str(self.rel_offset) + "]%0"
                    if header:
                        pad.move(0, 0)
                        theme_print(pad, header, width, "","", False, False)
                        try:
                            pad.move(1, 0)
                        except:
                            pass

                lines += 1

        # Render exceptions should be non-fatal. The worst
        # case scenario is that one story's worth of space
        # is going to be fucked up.

        except Exception as e:
            tb = traceback.format_exc()
            log.debug("Story exception:")
            log.debug("\n" + "".join(tb))

        # Reset theme counters
        theme_reset()

        return lines
