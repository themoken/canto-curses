# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from command import CommandHandler, command_format, generic_parse_error
from utility import silentfork

import logging
import curses

log = logging.getLogger("TAGLIST")

# TagList is the class renders a classical Canto list of tags into the given
# panel. It defers to the Tag class for the actual individual tag rendering.
# This is the level at which commands are taken and the backend is communicated
# with.

class TagList(CommandHandler):
    def init(self, pad, callbacks):
        # Drawing information
        self.pad = pad
        self.height, self.width = self.pad.getmaxyx()
        self.offset = 0

        # Callback information
        self.callbacks = callbacks

        self.tags = callbacks["get_var"]("curtags")

        # Holster for a list of items for batch operations.
        self.got_items = None

        self.keys = {
            " " : "add-window reader",
            "g" : "foritems & goto & item-state read & clearitems",
            "E" : "toggle tags_enumerated",
            "e" : "toggle enumerated",
            "R" : "item-state read *",
            "U" : "item-state -read *",
            "r" : "tag-state read",
            "u" : "tag-state -read",
            curses.KEY_NPAGE : "page-down",
            curses.KEY_PPAGE : "page-up",
            curses.KEY_DOWN : "rel-set-cursor 1",
            curses.KEY_UP : "rel-set-cursor -1",
        }

        self.refresh()

    def item_by_idx(self, idx):
        if idx < 0:
            return None

        spent = 0
        for tag in self.tags:
            ltag = len(tag)
            if spent + ltag > idx:
                return tag[ idx - spent ]
            spent += ltag
        return None

    def idx_by_item(self, item):
        spent = 0
        for tag in self.tags:
            if item in tag:
                return spent + tag.index(item)
            else:
                spent += len(tag)
        return None

    def all_items(self):
        r = []
        for tag in self.tags:
            r.extend(tag)
        return r

    # For Command processing
    def input(self, prompt):
        return self.callbacks["input"](prompt)

    # Prompt that ensures the items are enumerated first
    def eprompt(self):
        return self._var_set_prompt("enumerated", "items: ")

    # Will enumerate tags in the future.
    def teprompt(self):
        return self._var_set_prompt("tags_enumerated", "tags: ")

    def _var_set_prompt(self, var, prompt):
        # Ensure the items are enumerated
        t = self.callbacks["get_var"](var)
        self.callbacks["set_var"](var, True)

        r = self.input(prompt)

        # Reset var to previous value
        self.callbacks["set_var"](var, t)
        return r

    def uint(self, args):
        t, r = self._int(args, lambda : self.input("uint: "))
        if t:
            return (True, t, r)
        return (False, None, None)

    def listof_items(self, args):
        if not args:
            s = self.callbacks["get_var"]("selected")
            if s:
                return (True, [s], "")
            if self.got_items:
                return (True, self.got_items, "")
            else:
                args = self.eprompt()

        ints = self._listof_int(args, len(self.all_items()), self.eprompt)
        return (True, filter(None, [ self.item_by_idx(i) for i in ints ]), "")

    def listof_tags(self, args):
        if not args:
            s = self.callbacks["get_var"]("selected")
            if s:
                for tag in self.tags:
                    if s in tag:
                        return (True, [tag], "")
                raise Exception("Couldn't find tag of selection!")
            else:
                args = self.teprompt()

        ints = self._listof_int(args, len(self.tags), self.teprompt)
        return(True, [ self.tags[i] for i in ints ], "")

    def state(self, args):
        t, r = self._first_term(args, lambda : self.input("state: "))
        return (True, t, r)

    def item(self, args):
        t, r = self._int(args, lambda : self.input("item :"))
        if t:
            item = self.item_by_idx(t)
            if not item:
                log.error("There is no item %d" % t)
                return (False, None, None)
            return (True, item, r)
        return (False, None, None)

    @command_format("goto", [("items", "listof_items")])
    @generic_parse_error
    def goto(self, **kwargs):
        for item in kwargs["items"]:
            silentfork(None, item.content["link"])

    @command_format("tag-state", [("state", "state"),("tags","listof_tags")])
    @generic_parse_error
    def tag_state(self, **kwargs):
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

    @command_format("item-state", [("state", "state"),("items","listof_items")])
    @generic_parse_error
    def item_state(self, **kwargs):
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

    @command_format("set-cursor", [("idx", "item")])
    @generic_parse_error
    def set_cursor(self, **kwargs):
        self._set_cursor(kwargs["item"])

    # rel-set-cursor will move the cursor relative to its current position.
    # unlike set-cursor, it will both not allow the selection to be set to None
    # by going off-list.

    @command_format("rel-set-cursor", [("relidx", "uint")])
    @generic_parse_error
    def rel_set_cursor(self, **kwargs):
        sel = self.callbacks["get_var"]("selected")
        if sel:
            curidx = self.idx_by_item(sel)

        # curidx = -1 so that a `rel_set_cursor 1` (i.e. next) will 
        # select item 0
        else:
            curidx = -1

        item = self.item_by_idx(curidx + kwargs["relidx"])
        if not item:
            log.info("Will not relative scroll out of list.")
        else:
            self._set_cursor(item)

    def _set_cursor(self, item):
        # May end up as None
        sel = self.callbacks["get_var"]("selected")
        if item != sel:
            if sel:
                sel.unselect()

            self.callbacks["set_var"]("selected", item)

            if item:
                item.select()

                # If we have to adjust offset to 
                # keep selection on the screen,
                # refresh again.

                if self.offset > item.max_offset:
                    self.offset = item.max_offset
                elif self.offset < item.min_offset:
                    self.offset = item.min_offset

            self.refresh()
            self.callbacks["set_var"]("needs_redraw", True)

    # foritems gets a valid list of items by index.

    @command_format("foritems", [("items", "listof_items")])
    @generic_parse_error
    def foritems(self, **kwargs):
        self.got_items = kwargs["items"]

    # clearitems clears all the items set by foritems.

    @command_format("clearitems", [])
    @generic_parse_error
    def clearitems(self, **kwargs):
        self.got_items = None

    # simple command dispatcher.
    # TODO: This whole function could be made generic in CommandHandler

    def command(self, cmd):
        log.debug("TagList command: %s" % cmd)
        if cmd == "page-down":
            self.offset = min(self.offset + (self.height - 1), self.max_offset)
            self.callbacks["set_var"]("needs_redraw", True)
        elif cmd == "page-up":
            self.offset = max(self.offset - (self.height - 1), 0)
            self.callbacks["set_var"]("needs_redraw", True)

        elif cmd.startswith("goto"):
            self.goto(args=cmd)
        elif cmd.startswith("tag-state"):
            self.tag_state(args=cmd)
        elif cmd.startswith("item-state"):
            self.item_state(args=cmd)
        elif cmd.startswith("set-cursor"):
            self.set_cursor(args=cmd)
        elif cmd.startswith("rel-set-cursor"):
            self.rel_set_cursor(args=cmd)
        elif cmd.startswith("foritems"):
            self.foritems(args=cmd)
        elif cmd.startswith("clearitems"):
            self.clearitems(args=cmd)

    def refresh(self):
        self.max_offset = -1 * self.height
        idx = 0
        for tag in self.tags:
            ml = tag.refresh(self.width, idx)

            if len(ml) > 1:
                # Update each item's {min,max}_offset for being visible in case
                # they become selections.

                # Note: ml[0] == header, so current item's length = ml[i + 1]

                for i in xrange(len(tag)):
                    curpos = self.max_offset + sum(ml[0:i + 2])
                    tag[i].min_offset = max(curpos + 1, 0)
                    tag[i].max_offset = curpos + (self.height - ml[i + 1])

                    # Adjust for the floating header.
                    tag[i].max_offset -= ml[0]

            self.max_offset += sum(ml)
            idx += len(tag)

        # Ensure that calculated selected max offset
        # aren't outside of the general max offset

        sel = self.callbacks["get_var"]("selected")
        if sel and sel.max_offset > self.max_offset:
            sel.max_offset = self.max_offset

        self.redraw()

    def redraw(self):
        self.pad.erase()

        spent_lines = 0
        lines = self.height

        for tag in self.tags:
            taglines = tag.pad.getmaxyx()[0]

            # If we're still off screen up after last tag, but this
            # tag will put us over the top, partial render.

            if spent_lines < self.offset and\
                    taglines > (self.offset - spent_lines):
                start = (self.offset - spent_lines)

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
            elif spent_lines >= self.offset:

                # If we're *entirely* visible, render the whole thing
                if spent_lines < ((self.offset + self.height) - taglines):
                    dest_start = (spent_lines - self.offset)
                    tag.pad.overwrite(self.pad, 0, 0, dest_start, 0,\
                            dest_start + taglines - 1 , self.width - 1)

                # Elif we're partially visible (last tag).
                elif spent_lines < (self.offset + self.height):
                    dest_start = (spent_lines - self.offset)
                    maxr = dest_start +\
                            ((self.offset + self.height) - spent_lines)
                    tag.pad.overwrite(self.pad, 0, 0, dest_start, 0,\
                            maxr - 1, self.width - 1)
                    break

                # Else, we're off screen, and done.
                else:
                    break

            spent_lines += taglines

        self.callbacks["refresh"]()

    def is_input(self):
        return False

    def get_height(self, mheight):
        return mheight

    def get_width(self, mwidth):
        return mwidth


