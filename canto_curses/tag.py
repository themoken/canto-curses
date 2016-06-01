# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2016 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.hooks import call_hook, on_hook, unhook_all
from canto_next.plugins import Plugin, PluginHandler
from canto_next.rwlock import read_lock

from .locks import sync_lock, config_lock
from .theme import FakePad, WrapPad, theme_print, theme_reset, theme_border, prep_for_display
from .config import config
from .story import Story
from .color import cc

import traceback
import logging
import curses

log = logging.getLogger("TAG")

# TagCore provides the core tag functionality of keeping track of a list of IDs.

# The Tag class manages stories. Externally, it looks like a Tag takes IDs from
# the backend and renders an ncurses pad. No class other than Tag actually
# touches Story objects directly.

class TagPlugin(Plugin):
    pass

alltags = []

class Tag(PluginHandler, list):
    def __init__(self, tagcore, callbacks):
        list.__init__(self)
        PluginHandler.__init__(self)

        self.tagcore = tagcore
        self.tag = tagcore.tag
        self.is_tag = True
        self.updates_pending = 0

        self.pad = None
        self.footpad = None

        # Note that Tag() is only given the top-level CantoCursesGui
        # callbacks as it shouldn't be doing input / refreshing
        # itself.

        self.callbacks = callbacks.copy()

        # Modify our own callbacks so that *_tag_opt assumes
        # the current tag.

        self.callbacks["get_tag_opt"] =\
                lambda x : callbacks["get_tag_opt"](self.tag, x)
        self.callbacks["set_tag_opt"] =\
                lambda x, y : callbacks["set_tag_opt"](self.tag, x, y)
        self.callbacks["get_tag_name"] = lambda : self.tag

        # This could be implemented as a generic, top-level hook but then N
        # tags would have access to story objects they shouldn't have and
        # would have to check every items membership in self, which would be
        # pointless and time-consuming.

        self.callbacks["item_state_change"] =\
                self.on_item_state_change

        # Are there changes pending?
        self.changed = True

        self.selected = False
        self.marked = False

        # Information from last refresh
        self.footlines = 0
        self.extra_lines = 0
        self.width = 0

        self.collapsed = False
        self.border = False
        self.enumerated = False
        self.abs_enumerated = False

        # Formats for plugins to override
        self.pre_format = ""
        self.post_format = ""

        # Global indices (for enumeration)
        self.item_offset = -1
        self.visible_tag_offset = -1
        self.tag_offset = -1
        self.sel_offset = -1

        on_hook("curses_opt_change", self.on_opt_change, self)
        on_hook("curses_tag_opt_change", self.on_tag_opt_change, self)
        on_hook("curses_attributes", self.on_attributes, self)
        on_hook("curses_items_added", self.on_items_added, self)

        # Upon creation, this Tag adds itself to the
        # list of all tags.

        alltags.append(self)

        self.plugin_class = TagPlugin
        self.update_plugin_lookups()

    def die(self):
        log.debug("tag %s die()", self.tag)
        # Reset so items get die() called and everything
        # else is notified about items disappearing.

        for s in self:
            s.die()
        del self[:]

        alltags.remove(self)

        unhook_all(self)

    def on_item_state_change(self, item):
        self.need_redraw()

    def on_opt_change(self, opts):
        if "taglist" in opts and\
                ("tags_enumerated" in opts["taglist"] or\
                "tags_enumerated_absolute" in opts["taglist"] or\
                "border" in opts["taglist"]):
            self.need_redraw()

        if "tagobj" in opts:
            self.need_redraw()

        if "color" in opts or "style" in opts:
            self.need_redraw()

    def on_tag_opt_change(self, opts):
        if self.tag in list(opts.keys()):
            tc = opts[self.tag]
            if "collapsed" in tc:
                self.need_refresh()
            else:
                self.need_redraw()

    # Technically, we might want to hold sync_lock so that self[:] doesn't
    # change, but if we're syncing, the setting of needs_redraw isn't important
    # anymore, and if we're not, there's no issue.

    def on_attributes(self, attributes):
        for s in self:
            if s.id in attributes:
                self.need_redraw()
                break

    def on_items_added(self, tagcore, added):
        if tagcore == self.tagcore:
            cur_ids = self.get_ids()
            for story_id in added:
                if story_id not in cur_ids:
                    self.updates_pending += 1
            self.need_redraw()

    # We override eq so that empty tags don't evaluate
    # as equal and screw up things like enumeration.

    def __eq__(self, other):
        if other and (not other.is_tag or self.tag != other.tag):
            return False
        return list.__eq__(self, other)

    def __str__(self):
        return "%s" % self.tag[self.tag.index(':') + 1:]

    def get_id(self, id):
        for item in self:
            if item.id == id:
                return item

    def get_ids(self):
        return [ s.id for s in self ]

    # Inform the tag of global index of it's first item.
    def set_item_offset(self, offset):
        if self.item_offset != offset:
            self.item_offset = offset
            for i, item in enumerate(self):
                item.set_offset(offset + i)

    # Note that this cannot be short-cut (i.e.
    # copout if sel_offset is already equal)
    # because it's possible that it's the same
    # without the items having ever been updated.

    # Alternatively, we could reset them in
    # on_tag_opt_change, but since the sel
    # offset does not cause a redraw, there's
    # no point.

    def set_sel_offset(self, offset):
        self.sel_offset = offset

        if not self.callbacks["get_tag_opt"]("collapsed"):
            for i, item in enumerate(self):
                item.set_sel_offset(offset + i)

    def set_visible_tag_offset(self, offset):
        if self.visible_tag_offset != offset:
            self.visible_tag_offset = offset
            self.need_redraw()

    def set_tag_offset(self, offset):
        if self.tag_offset != offset:
            self.tag_offset = offset
            self.need_redraw()

    def select(self):
        if not self.selected:
            self.selected = True
            self.need_redraw()

    def unselect(self):
        if self.selected:
            self.selected = False
            self.need_redraw()

    def need_refresh(self):
        self.changed = True
        self.callbacks["set_var"]("needs_refresh", True)

    def need_redraw(self):
        self.changed = True
        self.callbacks["set_var"]("needs_redraw", True)

    def eval(self):
        # Make sure to strip out the category from category:name
        tag = self.tag.split(':', 1)[1]

        unread = len([s for s in self\
                if "canto-state" not in s.content or\
                "read" not in s.content["canto-state"]])

        s = ""
        if self.selected:
            s += cc("selected")

        if self.collapsed:
            s += "[+]"
        else:
            s += "[-]"

        s += " " + tag + " "

        s += "[" + cc("unread") + str(unread) + cc.end("unread") + "]"
        if self.updates_pending:
            s += " [" + cc("pending") + str(self.updates_pending) + cc.end("pending") + "]"

        if self.selected:
            s += cc.end("selected")

        return s

    def lines(self, width):
        if width == self.width and not self.changed:
            return self.lns

        taglist_conf = self.callbacks["get_opt"]("taglist")

        self.collapsed = self.callbacks["get_tag_opt"]("collapsed")
        self.border = taglist_conf["border"]
        self.enumerated = taglist_conf["tags_enumerated"]
        self.abs_enumerated = taglist_conf["tags_enumerated_absolute"]

        extra_tags = self.callbacks["get_tag_conf"](self.tag)['extra_tags']

        self.pad = None
        self.footpad = None
        self.width = width
        self.changed = False

        self.evald_string = self.eval()

        self.lns = self.render_header(width, FakePad(width))
        self.footlines = self.render_footer(width, FakePad(width))

        return self.lns

    def pads(self, width):
        if self.pad and (self.footpad or not self.footlines) and not self.changed:
            return self.lns

        self.pad = curses.newpad(self.lines(width), width)
        self.render_header(width, WrapPad(self.pad))

        if self.footlines:
            self.footpad = curses.newpad(self.footlines, width)
            self.render_footer(width, WrapPad(self.footpad))
        return self.lns

    def render_header(self, width, pad):
        s = self.evald_string
        lines = 0

        try:
            while s:
                s = theme_print(pad, s, width, "", "")

                if lines == 0:
                    header = ""
                    if self.enumerated:
                        header += cc("enum_hints") + "[" + str(self.visible_tag_offset) + "]%0"
                    if self.abs_enumerated:
                        header += cc("enum_hints") + "[" + str(self.tag_offset) + "]%0"
                    if header:
                        pad.move(0, 0)
                        theme_print(pad, header, width, "", "", False, False)
                        try:
                            pad.move(1, 0)
                        except:
                            pass
                lines += 1

            if not self.collapsed and self.border:
                theme_print(pad, theme_border("ts") * (width - 2), width,\
                        "%B"+ theme_border("tl"), theme_border("tr") + "%b")
                lines += 1
        except Exception as e:
            tb = traceback.format_exc()
            log.debug("Tag exception:")
            log.debug("\n" + "".join(tb))

        theme_reset()

        return lines

    def render_footer(self, width, pad):
        if not self.collapsed and self.border:
            theme_print(pad, theme_border("bs") * (width - 2), width,\
                    "%B" + theme_border("bl"), theme_border("br") + "%b")
            theme_reset()
            return 1
        return 0

    # Synchronize this Tag with its TagCore

    def sync(self, force=False):
        if force or self.tagcore.changes:
            sel = self.callbacks["get_var"]("selected")

            self.tagcore.lock.acquire_read()

            self.tagcore.ack_changes()

            # Get sorted ids, along with their (unsorted) positions in the
            # original lists.

            sorted_ids = [ (x, x.id, i) for (i, x) in enumerate(self) ]
            sorted_ids.sort(key=lambda x: x[1])

            tagcore_sorted_ids = list(enumerate(self.tagcore))
            tagcore_sorted_ids.sort(key=lambda x: x[1])

            new_ids = []
            current_stories = []
            old_stories = []

            for story, s_id, place in sorted_ids:
                while tagcore_sorted_ids and s_id > tagcore_sorted_ids[0][1]:
                    new_ids.append(tagcore_sorted_ids.pop(0))

                if not tagcore_sorted_ids or s_id < tagcore_sorted_ids[0][1]:
                    if sel and (not sel.is_tag) and (s_id == sel.id):

                        # If we preserve the selection in an "undead" state, then
                        # we keep set tagcore changed so that the next sync operation
                        # will re-evaluate it.

                        self.tagcore.changed()
                        place = -1
                        current_stories.append((place, story))
                    else:
                        old_stories.append(story)
                else:
                    place = tagcore_sorted_ids.pop(0)[0]
                    current_stories.append((place, story))

            # Grab any remaining new items
            new_ids += tagcore_sorted_ids

            self.tagcore.lock.release_read()

            new_stories = [ (p, Story(self, x, self.callbacks)) for (p, x) in new_ids ]

            call_hook("curses_stories_added", [ self, [ x for (p, x) in new_stories ]])

            del self[:]

            conf = config.get_conf()
            if conf["update"]["style"] == "maintain" or self.tagcore.was_reset:
                self.tagcore.was_reset = False
                current_stories += new_stories
                current_stories.sort()
                self.extend([ x[1] for x in current_stories ])
            else:
                current_stories.sort()
                new_stories.sort()
                if conf["update"]["style"] == "append":
                    current_stories += new_stories
                    self.extend([ x[1] for x in current_stories ])
                else:
                    new_stories += current_stories
                    self.extend([ x[1] for x in new_stories ])

            for story in old_stories:
                story.die()

            # Properly dispose of the remaining stories

            call_hook("curses_stories_removed", [ self, old_stories ])

            # Trigger a refresh so that classes above (i.e. TagList) will remap
            # items

            self.need_refresh()

        # Pass the sync onto story objects
        for s in self:
            s.sync()

        self.updates_pending = 0
