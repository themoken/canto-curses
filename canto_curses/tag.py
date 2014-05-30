# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.hooks import call_hook, on_hook, remove_hook
from canto_next.rwlock import read_lock

from .locks import sync_lock
from .parser import parse_conditionals, eval_theme_string, prep_for_display
from .theme import FakePad, WrapPad, theme_print, theme_reset, theme_border
from .config import config, DEFAULT_TAG_FSTRING
from .story import Story

import traceback
import logging
import curses

log = logging.getLogger("TAG")

# TagCore provides the core tag functionality of keeping track of a list of IDs.

# The Tag class manages stories. Externally, it looks
# like a Tag takes IDs from the backend and renders an ncurses pad. No class
# other than Tag actually touches Story objects directly.

class Tag(list):
    def __init__(self, tagcore, callbacks):
        list.__init__(self)
        self.tagcore = tagcore
        self.tag = tagcore.tag

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
        self.lines = 0
        self.footlines = 0
        self.extra_lines = 0
        self.width = 0

        # Global indices (for enumeration)
        self.item_offset = None
        self.visible_tag_offset = None
        self.tag_offset = None
        self.sel_offset = None

        on_hook("curses_opt_change", self.on_opt_change)
        on_hook("curses_tag_opt_change", self.on_tag_opt_change)
        on_hook("curses_attributes", self.on_attributes)

        # Upon creation, this Tag adds itself to the
        # list of all tags.

        # XXX: FUCKING LOCK IT
        callbacks["get_var"]("alltags").append(self)
        config.eval_tags()

        self.sync(True)

    def die(self):
        # Reset so items get die() called and everything
        # else is notified about items disappearing.

        self.reset()
        remove_hook("curses_opt_change", self.on_opt_change)
        remove_hook("curses_tag_opt_change", self.on_tag_opt_change)
        remove_hook("curses_attributes", self.on_attributes)

    def on_item_state_change(self, item):
        self.need_redraw()

    def on_opt_change(self, opts):
        if "taglist" in opts and\
                ("tags_enumerated" in opts["taglist"] or\
                "tags_enumerated_absolute" in opts["taglist"] or\
                "border" in opts["taglist"]):
            self.need_redraw()

        if "tag" in opts:
            self.need_redraw()

    def on_tag_opt_change(self, opts):
        if self.tag in list(opts.keys()):
            tc = opts[self.tag]
            if "collapsed" in tc:
                self.need_refresh()
            else:
                self.need_redraw()

    def on_attributes(self, attributes):
        for s in self:
            if s.id in attributes:
                self.need_redraw()
                break

    # We override eq so that empty tags don't evaluate
    # as equal and screw up things like enumeration.

    def __eq__(self, other):
        if not hasattr(other, "tag") or self.tag != other.tag:
            return False
        return list.__eq__(self, other)

    def __str__(self):
        return "tag: %s" % self.tag

    def get_id(self, id):
        for item in self:
            if item.id == id:
                return item
        return None

    def get_ids(self):
        return [ s.id for s in self ]

    # Take a list of ordered ids and reorder ourselves, without generating any
    # unnecessary add/remove hooks.

    def reorder(self, ids):
        cur_stories = [ s for s in self ]

        # Perform the actual reorder.
        stories = [ self.get_id(id) for id in ids ]

        del self[:]
        list.extend(self, stories)

        # Deal with items that aren't listed. Usually this happens if the item
        # would be filtered, but is protected for some reason (like selection)

        # NOTE: This is bad behavior, but if we don't retain these items, other
        # code will crap-out expecting this item to exist. Built-in transforms
        # are hardened to never discard items with the filter-immune reason,
        # like selection, so this is just for bad user transforms.

        for s in cur_stories:
            if s not in self:
                log.warn("Warning: A filter is filtering filter-immune items.")
                log.warn("Compensating. This may cause items to jump unexpectedly.")
                list.append(self, s)

        log.debug("Self: %s" % [ s for s in self ])

        # Handle updating story information.
        for i, story in enumerate(self):
            story.set_rel_offset(i)
            story.set_offset(self.item_offset + i)
            story.set_sel_offset(self.sel_offset + i)

        # Request redraw to update item counts.
        self.need_redraw()

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

    def do_changes(self, width):
        if width != self.width or self.changed:
            self.refresh(width)

    def refresh(self, width):
        self.width = width

        lines = self.render_header(width, FakePad(width))

        self.pad = curses.newpad(lines, width)
        self.render_header(width, WrapPad(self.pad))

        self.lines = lines

        lines = self.render_footer(width, FakePad(width))

        if lines:
            self.footpad = curses.newpad(lines, width)
            self.render_footer(width, WrapPad(self.footpad))
        else:
            self.footpad = None

        self.footlines = lines

        self.changed = False

    def render_header(self, width, pad):
        tag_conf = self.callbacks["get_opt"]("tag")
        taglist_conf = self.callbacks["get_opt"]("taglist")
        collapsed = self.callbacks["get_tag_opt"]("collapsed")

        # Make sure to strip out the category from category:name
        tag = self.tag.split(':', 1)[1]

        unread = len([s for s in self\
                if "canto-state" not in s.content or\
                "read" not in s.content["canto-state"]])

        extra_tags = self.callbacks["get_tag_conf"](self.tag)['extra_tags']

        # These are escapes that are handled in the theme_print
        # lower in the function and should remain present after
        # evaluation.

        passthru = {}
        for c in "RrDdUuBbSs012345678":
            passthru[c] = "%" + c

        for attr in [ "selected", "unselected", "selected_end", "unselected_end" ]:
            passthru[attr] = tag_conf[attr]

        fstring = tag_conf["format"]
        try:
            parsed = parse_conditionals(fstring)
        except Exception as e:
            log.warn("Failed to parse conditionals in fstring: %s" %
                    fstring)
            log.warn("\n" + "".join(traceback.format_exc()))
            log.warn("Falling back to default.")
            parsed = parse_conditionals(DEFAULT_TAG_FSTRING)

        values = { 'en' : taglist_conf["tags_enumerated"],
                    'aen' : taglist_conf["tags_enumerated_absolute"],
                    'c' : collapsed,
                    't' : tag,
                    'sel' : self.selected,
                    'n' : unread,
                    'to' : self.tag_offset,
                    'vto' : self.visible_tag_offset,
                    "extra_tags" : extra_tags,
                    'tag' : self,
                    'prep' : prep_for_display}

        # Prep all text values for display.

        for value in list(values.keys()):
            if type(values[value]) in [str, str]:
                values[value] = prep_for_display(values[value])

        values.update(passthru)

        try:
            s = eval_theme_string(parsed, values)
        except Exception as e:
            log.warn("Failed to evaluate fstring: %s" % fstring)
            log.warn("\n" + "".join(traceback.format_exc()))
            log.warn("Falling back to default")

            parsed = parse_conditionals(DEFAULT_TAG_FSTRING)
            s = eval_theme_string(parsed, values)

        lines = 0

        while s:
            s = theme_print(pad, s, width, "", "")
            lines += 1

        if not collapsed and taglist_conf["border"]:
            theme_print(pad, theme_border("ts") * (width - 2), width,\
                    "%B%1"+ theme_border("tl"), theme_border("tr") + "%0%b")
            lines += 1

        theme_reset()

        return lines

    def render_footer(self, width, pad):
        taglist_conf = self.callbacks["get_opt"]("taglist")
        collapsed = self.callbacks["get_tag_opt"]("collapsed")

        if not collapsed and taglist_conf["border"]:
            theme_print(pad, theme_border("bs") * (width - 2), width,\
                    "%B%1" + theme_border("bl"), theme_border("br") + "%0%b")
            theme_reset()
            return 1
        return 0

    # Synchronize this Tag with its TagCore

    @read_lock(sync_lock)
    def sync(self, force=False):
        if force or self.tagcore.changed:
            my_ids = [ s.id for s in self ]
            new_stories = []

            self.tagcore.lock.acquire_read()

            for id in self.tagcore:
                if id in my_ids:
                    s = self[my_ids.index(id)]
                    new_stories.append(s)
                    self.remove(s)
                    my_ids.remove(s.id)
                else:
                    new_stories.append(Story(id, self.callbacks))

            self.tagcore.lock.release_read()

            # Properly dispose of the remaining stories
            for s in self:
                s.die()
            del self[:]

            self.extend(new_stories)

            # Trigger a refresh so that classes above (i.e. TagList) will remap
            # items

            self.need_refresh()

        # Pass the sync onto story objects
        for s in self:
            s.sync()
