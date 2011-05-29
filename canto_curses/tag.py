# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.hooks import call_hook, on_hook, remove_hook

from theme import FakePad, WrapPad, theme_print
from story import Story

import logging
import curses

log = logging.getLogger("TAG")

# The Tag class manages stories. Externally, it looks
# like a Tag takes IDs from the backend and renders an ncurses pad. No class
# other than Tag actually touches Story objects directly.

class Tag(list):
    def __init__(self, tag, callbacks):
        list.__init__(self)
        self.tag = tag
        self.pad = None

        # Note that Tag() is only given the top-level CantoCursesGui
        # callbacks as it shouldn't be doing input / refreshing
        # itself.

        self.callbacks = callbacks.copy()

        # Modify our own callbacks so that *_tag_opt assumes
        # the current tag.

        self.callbacks["get_tag_opt"] =\
                lambda x : callbacks["get_tag_opt"](self, x)
        self.callbacks["set_tag_opt"] =\
                lambda x, y : callbacks["set_tag_opt"](self, x, y)

        # Are there changes pending?
        self.changed = True

        self.selected = False

        # Information from last refresh
        self.lines = 0
        self.width = 0

        # Global indices (for enumeration)
        self.item_offset = 0
        self.visible_tag_offset = 0
        self.tag_offset = 0
        self.sel_offset = 0

        on_hook("opt_change", self.on_opt_change)
        on_hook("tag_opt_change", self.on_tag_opt_change)

        # Upon creation, this Tag adds itself to the
        # list of all tags.

        callbacks["get_var"]("alltags").append(self)

    def die(self):
        # Reset so items get die() called and everything
        # else is notified about items disappearing.

        self.reset()
        remove_hook("opt_change", self.on_opt_change)
        remove_hook("tag_opt_change", self.on_tag_opt_change)

    def on_opt_change(self, opts):
        if "taglist.tags_enumerated" in opts or \
                "taglist.tags_enumerated_absolute" in opts:
            self.need_redraw()

    def on_tag_opt_change(self, tag, opts):
        if tag == self:
            self.need_redraw()

    # We override eq so that empty tags don't evaluate
    # as equal and screw up things like enumeration.

    def __eq__(self, other):
        if self.tag != other.tag:
            return False
        return list.__eq__(self, other)

    # Create Story from ID before appending to list.

    def add_items(self, ids):
        added = []
        for id in ids:
            s = Story(id, self.callbacks)
            self.append(s)
            added.append(s)

            rel = len(self) - 1
            s.set_rel_offset(rel)
            s.set_offset(self.item_offset + rel)
            s.set_sel_offset(self.sel_offset + rel)

        call_hook("items_added", [ self, added ] )

    # Remove Story based on ID

    def remove_items(self, ids):
        removed = []

        # Copy self so we can remove from self
        # without screwing up iteration.

        for idx, item in enumerate(self[:]):
            if item.id in ids:
                log.debug("removing: %s" % (item.id,))

                list.remove(self, item)
                item.die()
                removed.append(item)

        # Update indices of items.
        for i, story in enumerate(self):
            story.set_rel_offset(i)
            story.set_offset(self.item_offset + i)
            story.set_sel_offset(self.sel_offset + i)

        call_hook("items_removed", [ self, removed ] )

    # Remove all stories from this tag.

    def reset(self):
        for item in self:
            item.die()

        call_hook("items_removed", [ self, self[:] ])
        del self[:]

    def get_id(self, id):
        for item in self:
            if item.id == id:
                return item
        return None

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

    def need_redraw(self):
        self.changed = True
        self.callbacks["set_var"]("needs_redraw", True)

    def do_changes(self, width):
        if width != self.width or self.changed:
            self.refresh(width)

    def refresh(self, width):
        self.width = width

        lines = self.render_header(width, FakePad(width))

        self.pad = curses.newpad(lines, width)
        self.render_header(width, WrapPad(self.pad))

        self.lines = lines
        self.changed = False

    def render_header(self, width, pad):
        enumerated = self.callbacks["get_opt"]("taglist.tags_enumerated")
        enumerated_absolute =\
            self.callbacks["get_opt"]("taglist.tags_enumerated_absolute")

        # Make sure to strip out the category from category:name
        header = self.tag.split(':', 1)[1]

        if self.callbacks["get_tag_opt"]("collapsed"):
            header = "[+] " + header
        else:
            header = "[-] " + header

        # Tags can be both absolute and relatively enumerated at once,
        # in this case the absolute enumeration is the first listed and thus
        # it's added to the front of the string last.

        if enumerated:
            header = ("[%d] " % self.visible_tag_offset) + header

        if enumerated_absolute:
            header = ("[%d] " % self.tag_offset) + header

        if self.selected:
            header = "%R" + header + "%r"

        header += u"\n"

        lines = 0

        while header:
            header = theme_print(pad, header, width, u"", u"")
            lines += 1

        return lines
