# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import Plugin
from command import command_format
from guibase import GuiBase
from reader import Reader

import logging
import curses
import os

log = logging.getLogger("TAGLIST")

# TagList is the class renders a classical Canto list of tags into the given
# panel. It defers to the Tag class for the actual individual tag rendering.
# This is the level at which commands are taken and the backend is communicated
# with.

class TagListPlugin(Plugin):
    pass

class TagList(GuiBase):
    def __init__(self):
        GuiBase.__init__(self)
        self.plugin_class = TagListPlugin

    def init(self, pad, callbacks):
        # Drawing information
        self.pad = pad
        self.height, self.width = self.pad.getmaxyx()

        # Callback information
        self.callbacks = callbacks

        # Holster for a list of items for batch operations.
        self.got_items = None

        self.refresh()

    # We start with a number of convenient lookup, listing,
    # and user prompting functions.

    def item_by_idx(self, idx):
        if idx < 0:
            raise Exception("Negative indices not allowed!")

        spent = 0
        for tag in self.tags:
            ltag = len(tag)
            if spent + ltag > idx:
                return tag[ idx - spent ]
            spent += ltag
        raise Exception("Couldn't find item with idx: %d" % idx)

    def idx_by_item(self, item):
        spent = 0
        for tag in self.tags:
            if item in tag:
                return spent + tag.index(item)
            else:
                spent += len(tag)
        raise Exception("Couldn't find idx of item: %s" % item)

    def tag_by_item(self, item):
        for tag in self.tags:
            if item in tag:
                return tag
        raise Exception("Couldn't find tag of item: %s" % item)

    def all_items(self):
        for tag in self.tags:
            for story in tag:
                yield story

    def all_items_reversed(self):
        for tag in reversed(self.tags):
            for story in reversed(tag):
                yield story

    def first_visible_item(self):
        offset = self.callbacks["get_var"]("offset")

        for item in self.all_items():
            if offset >= item.min_offset and offset <= item.max_offset:
                return item

    # Prompt that ensures the items are enumerated first
    def eprompt(self, prompt):
        return self._cfg_set_prompt("story.enumerated", prompt)

    # Prompt that enumerates only items in a single tag.
    def tag_eprompt(self, tag, prompt):
        return self._tag_cfg_set_prompt(tag, "enumerated", prompt)

    # Enumerates visible tags.
    def teprompt(self, prompt):
        return self._cfg_set_prompt("taglist.tags_enumerated", prompt)

    # Enumerates all tags.
    def teprompt_absolute(self, prompt):
        return self._cfg_set_prompt("taglist.tags_enumerated_absolute",
                prompt)

    # Following we have a number of command helpers. These allow
    # commands to take lists of items, tags, or tag subranges of items in
    # addition to singular items, and possible item states, etc.

    def _single_tag(self, args, taglist, prompt):
        tag, args = self._int(args, prompt)

        # If we failed to get a valid integer, bail.
        if tag == None or tag < 0 or tag >= len(taglist):
            return (None, None, "")

        return (True, taglist[tag], args)

    def single_tag(self, args):
        vistags = self.callbacks["get_var"]("taglist_visible_tags")
        prompt = lambda : self.teprompt("tag: ")
        return self._single_tag(args, vistags, prompt)

    def single_tag_absolute(self, args):
        prompt = lambda : self.teprompt_absolute("tag: ")
        return self._single_tag(args, self.tags, prompt)

    def listof_items(self, args):
        s = self.callbacks["get_var"]("selected")

        if not args:
            if s:
                return (True, [s], "")
            if self.got_items != None:
                log.debug("listof_items falling back on got_items")
                return (True, self.got_items, "")

        # Lookahead. If the first term is t: then we're going to grab
        # items relative to a tag.

        if args and args.startswith("t:") or args.startswith("T:"):
            lookup_type, args = args[0], args[2:]

            # Relative tag lookup.
            if lookup_type == "t":
                valid, tag, args = self.single_tag(args)
            else:
                valid, tag, args = self.single_tag_absolute(args)

            if not valid:
                log.error("listof_items t: found, but no valid tag!")
                return (False, None, "")

            if s and s in tag:
                curint = tag.index(s)
            else:
                curint = 0

            ints = self._listof_int(args, curint, len(tag),
                    lambda : self.tag_eprompt(tag, "items: "))
            return (True, [ tag[i] for i in ints ], "")
        else:
            if s:
                curint = self.idx_by_item(s)
            else:
                curint = 0

            ints = self._listof_int(args, curint, len(list(self.all_items())),\
                    lambda : self.eprompt("items: "))
            return (True, [ self.item_by_idx(i) for i in ints ], "")

    def listof_tags(self, args):
        s = self.callbacks["get_var"]("selected")
        got_tag = None

        if s:
            got_tag = self.tag_by_item(s)

        # If we have a selected tag and no args, return it automatically.
        if not args and got_tag:
            return (True, [got_tag], "")

        if got_tag:
            curint = self.tags.index(got_tag)
        else:
            curint = 0

        ints = self._listof_int(args, curint, len(self.tags),\
                lambda : self.teprompt("tags: "))
        return(True, [ self.tags[i] for i in ints ], "")

    def state(self, args):
        t, r = self._first_term(args, lambda : self.input("state: "))
        return (True, t, r)

    def item(self, args):
        t, r = self._int(args, lambda : self.eprompt("item: "))
        if t != None:
            item = self.item_by_idx(t)
            if not item:
                log.error("There is no item %d" % t)
                return (False, None, None)
            return (True, item, r)
        return (False, None, None)

    def sel_or_item(self, args):
        if not args:
            s = self.callbacks["get_var"]("selected")
            if s:
                return (True, s, "")
            if self.got_items:
                if len(self.got_items) > 1:
                    log.info("NOTE: Only using first of selected items.")
                return (True, self.got_items[0], "")
        return self.item(args)

    @command_format([("items", "listof_items")])
    def cmd_goto(self, **kwargs):
        self._goto([item.content["link"] for item in kwargs["items"]])

    @command_format([("state", "state"),("tags","listof_tags")])
    def cmd_tag_state(self, **kwargs):
        attributes = {}
        for tag in kwargs["tags"]:
            for item in tag:
                if item.handle_state(kwargs["state"]):
                    attributes[item.id] =\
                            { "canto-state" : item.content["canto-state"]}

        if attributes != {}:
            self.refresh()
            self.callbacks["set_var"]("needs_redraw", True)
            self.callbacks["write"]("SETATTRIBUTES", attributes)

    # item-state: Add/remove state for multiple items.

    @command_format([("state", "state"),("items","listof_items")])
    def cmd_item_state(self, **kwargs):
        attributes = {}
        for item in kwargs["items"]:
            if item.handle_state(kwargs["state"]):
                attributes[item.id] =\
                        { "canto-state" : item.content["canto-state"] }

        # Propagate state changes to the backend.

        if attributes:
            self.refresh()
            self.callbacks["set_var"]("needs_redraw", True)
            self.callbacks["write"]("SETATTRIBUTES", attributes)

    @command_format([])
    def cmd_unset_cursor(self, **kwargs):
        self._set_cursor(None)

    @command_format([("idx", "item")])
    def cmd_set_cursor(self, **kwargs):
        self._set_cursor(kwargs["item"])

    # rel-set-cursor will move the cursor relative to its current position.
    # unlike set-cursor, it will both not allow the selection to be set to None
    # by going off-list.

    @command_format([("relidx", "int")])
    def cmd_rel_set_cursor(self, **kwargs):
        sel = self.callbacks["get_var"]("selected")
        if sel:
            curidx = self.idx_by_item(sel)

        # If unset, try to set curidx such that a 'next' (rel_set_cursor +1)
        # will select the first item on screen.

        else:
            fi = self.first_visible_item()
            if fi:
                curidx = self.idx_by_item(fi) - 1

            # No visible items.
            else:
                curidx = -1

        try:
            item = self.item_by_idx(curidx + kwargs["relidx"])
        except:
            log.info("Will not relative scroll out of list.")
        else:
            self._set_cursor(item)

    # Ensures that offset is set such that the current item
    # is visible.

    def adjust_offset(self, item):
        offset = self.callbacks["get_var"]("offset")

        if offset > item.max_offset:
            offset = min(item.max_offset, self.max_offset)
        elif offset < item.min_offset:
            offset = max(item.min_offset, 0)

        self.callbacks["set_var"]("offset", offset)

    def _set_cursor(self, item):
        # May end up as None
        sel = self.callbacks["get_var"]("selected")
        if item != sel:
            if sel:
                sel.unselect()

            self.callbacks["set_var"]("selected", item)

            if item:
                item.select()

                # Adjust offset to keep selection on the screen
                self.adjust_offset(item)

            self.refresh()
            self.callbacks["set_var"]("needs_redraw", True)

    # foritems gets a valid list of items by index.

    @command_format([("items", "listof_items")])
    def cmd_foritems(self, **kwargs):
        self.got_items = kwargs["items"]

    @command_format([("item", "sel_or_item")])
    def cmd_foritem(self, **kwargs):
        log.debug("setting got_items: %s" % [ kwargs["item"] ])
        self.got_items = [ kwargs["item"] ]

    # clearitems clears all the items set by foritems.

    @command_format([])
    def cmd_clearitems(self, **kwargs):
        self.got_items = None

    @command_format([])
    def cmd_page_up(self, **kwargs):
        offset = self.callbacks["get_var"]("offset")
        scroll = self.height - 1

        sel = self.callbacks["get_var"]("selected")
        if sel:
            newsel = None
            for item in self.all_items_reversed():
                if item.max_offset <= (sel.max_offset - scroll):
                    break
                newsel = item

            if newsel:
                item_offset = sel.max_offset - offset
                offset = min(newsel.max_offset - item_offset, self.max_offset)
        else:
            offset -= scroll

        offset = max(offset, 0)

        # _set_cursor relies on the offset var, set it first.
        self.callbacks["set_var"]("offset", offset)
        self._set_cursor(newsel)
        self.callbacks["set_var"]("needs_redraw", True)

    @command_format([])
    def cmd_page_down(self, **kwargs):
        offset = self.callbacks["get_var"]("offset")
        scroll = self.height - 1

        sel = self.callbacks["get_var"]("selected")
        if sel:
            newsel = None
            for item in self.all_items():
                if item.max_offset >= (sel.max_offset + scroll):
                    break
                newsel = item

            if newsel:
                item_offset = sel.max_offset - offset
                offset = newsel.max_offset - item_offset
        else:
            offset += scroll

        offset = min(offset, self.max_offset)

        # _set_cursor relies on the offset var, set it first.
        self.callbacks["set_var"]("offset", offset)
        self._set_cursor(newsel)
        self.callbacks["set_var"]("needs_redraw", True)

    @command_format([("item", "sel_or_item")])
    def cmd_reader(self, **kwargs):
        self.callbacks["set_var"]("reader_item", kwargs["item"])
        self.callbacks["set_var"]("reader_offset", 0)
        self.callbacks["add_window"](Reader)

    def set_visible_tags(self):
        hide_empty = self.callbacks["get_opt"]("taglist.hide_empty_tags")

        t = []
        for tag in self.tags:
            if hide_empty and len(tag) == 0:
                continue
            t.append(tag)

        self.callbacks["set_var"]("taglist_visible_tags", t)

    def refresh(self):
        self.tags = self.callbacks["get_var"]("curtags")
        self.max_offset = -1 * self.height
        idx = 0

        self.set_visible_tags()
        for tag in self.callbacks["get_var"]("taglist_visible_tags"):
            ml = tag.refresh(self.width, idx)

            if len(ml) > 1:
                # Update each item's {min,max}_offset for being visible in case
                # they become selections.

                # Note: ml[0] == header, so current item's length = ml[i + 1]

                # Note: min/max_offsets are theoretical (i.e. they don't
                # have to exist between 0 and self.max_offset.

                for i in xrange(len(tag)):
                    curpos = self.max_offset + sum(ml[0:i + 2])
                    tag[i].min_offset = curpos + 1
                    tag[i].max_offset = curpos + (self.height - ml[i + 1])

                    # Adjust for the floating header.
                    tag[i].max_offset -= ml[0]

            self.max_offset += sum(ml)
            idx += len(tag)

        # If we have less than a screenful of
        # content, set max_offset to pin it to the top.

        if self.max_offset <= 0:
            self.max_offset = 0
        else:
            self.max_offset += 1

        # If we've got a selection make sure it's
        # still going to be onscreen.

        sel = self.callbacks["get_var"]("selected")
        if sel:
            self.adjust_offset(sel)

        self.redraw()

    def redraw(self):
        self.pad.erase()

        offset = self.callbacks["get_var"]("offset")
        spent_lines = 0

        # We use 'done' when we know we've rendered all the
        # tags we can. We can't just 'break' from the loop
        # or spent_lines accounting will fuck up.

        done = False

        lines = self.height

        for tag in self.callbacks["get_var"]("taglist_visible_tags"):

            taglines = tag.pad.getmaxyx()[0]

            # If we're still off screen up after last tag, but this
            # tag will put us over the top, partial render.

            if spent_lines < offset and taglines > (offset - spent_lines):
                start = (offset - spent_lines)

                # min() so we don't try to write too much if the
                # first tag is also the only tag on screen.
                maxr = min(taglines - start, self.height)

                tag.pad.overwrite(self.pad, start, 0, 0, 0,\
                        maxr - 1, self.width - 1)

                # This is first tag, render floating tag header.
                headerlines = tag.header_pad.getmaxyx()[0]
                maxr = min(headerlines, self.height)

                tag.header_pad.overwrite(self.pad, 0, 0, 0, 0,\
                        maxr - 1, self.width - 1)

            # Elif we're possible visible
            elif spent_lines >= offset:

                # If we're *entirely* visible, render the whole thing
                if spent_lines < ((offset + self.height) - taglines):
                    dest_start = (spent_lines - offset)
                    tag.pad.overwrite(self.pad, 0, 0, dest_start, 0,\
                            dest_start + taglines - 1 , self.width - 1)

                # Elif we're partially visible (last tag).
                elif spent_lines < (offset + self.height):
                    dest_start = (spent_lines - offset)
                    maxr = dest_start + ((offset + self.height) - spent_lines)
                    tag.pad.overwrite(self.pad, 0, 0, dest_start, 0,\
                            maxr - 1, self.width - 1)
                    done = True

                # Else, we're off screen, and done.
                else:
                    done = True

            spent_lines += taglines
            if done:
                break

        if not spent_lines:
            self.pad.addstr("All tags empty.")

        self.callbacks["refresh"]()

    def is_input(self):
        return False

    def get_opt_name(self):
        return "taglist"

    def get_height(self, mheight):
        return mheight

    def get_width(self, mwidth):
        return mwidth
