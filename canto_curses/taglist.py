# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import Plugin
from canto_next.hooks import on_hook, remove_hook, call_hook

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

        # First (at least partially) visible object
        self.first_obj = None

        # Hooks
        on_hook("eval_tags_changed", self.refresh)
        on_hook("items_added", self.on_items_added)
        on_hook("items_removed", self.on_items_removed)

        self.update_tag_lists()

        # Inform the tags that our size could now
        # be different than the last time they were
        # refreshed.

        for tag in self.tags:
            tag.refresh(self.width)

    def die(self):
        log.debug("Cleaning up hooks...")
        remove_hook("eval_tags_changed", self.refresh)
        remove_hook("items_added", self.on_items_added)
        remove_hook("items_removed", self.on_items_removed)

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

    def all_visible_tags_and_items(self):
        for tag in self.callbacks["get_var"]("taglist_visible_tags"):
            yield tag
            for story in tag:
                yield story

    def first_visible_item(self):
        offset = self.callbacks["get_var"]("offset")

        for item in self.all_items():
            if offset >= item.min_offset:
                return item

    def on_items_added(self, tag, items):
        # Items being added implies we need to remap them
        self.callbacks["set_var"]("needs_refresh", True)

        # The rest of this function is about trying to
        # maintain the selection.

        sel = self.callbacks["get_var"]("selected")
        if sel:
            return

        old_sel = self.callbacks["get_var"]("old_selected")
        if not old_sel or old_sel not in items:
            return

        # Re-reference. The stories equality is based
        # entirely on its ID value, but we still need
        # to make sure we have the new item.

        new_sel = items[items.index(old_sel)]
        new_sel.select()

        self.callbacks["set_var"]("selected", new_sel)
        self.callbacks["set_var"]("old_selected", None)

    def on_items_removed(self, tag, items):
        # Items being removed implies we need to remap them.
        self.callbacks["set_var"]("needs_refresh", True)

        sel = self.callbacks["get_var"]("selected")
        if sel in items:
            self.callbacks["set_var"]("selected", None)
            self.callbacks["set_var"]("old_selected", sel)

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
        s = self.callbacks["get_var"]("selected")

        curint = 0
        if s:
            curtag = self.tag_by_item(s)
            if curtag in taglist:
                curint = taglist.index(curtag)

        tag, args = self._int(args, curint, len(taglist), prompt)

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

        visible_tags = self.callbacks["get_var"]("taglist_visible_tags")
        return(True, [ visible_tags[i] for i in ints ], "")

    def state(self, args):
        t, r = self._first_term(args, lambda : self.input("state: "))
        return (True, t, r)

    def item(self, args):
        s = self.callbacks["get_var"]("selected")

        if s:
            curint = self.idx_by_item(s)
        else:
            curint = 0

        t, r = self._int(args, curint, len(list(self.allitems())),\
                lambda : self.eprompt("item: "))

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

    # Wrapper that will update self.first_obj.

    def set_offset(self, offset):
        cur_offset = self.callbacks["get_var"]("offset")

        while self.first_obj:
            if self.first_obj.next_obj and self.first_obj.max_draw_offset < offset:
                self.first_obj = self.first_obj.next_obj
            elif self.first_obj.prev_obj and self.first_obj.prev_obj.max_draw_offset >= offset:
                self.first_obj = self.first_obj.prev_obj
            else:
                break

        self.callbacks["set_var"]("offset", offset)
        if cur_offset != offset:
            self.redraw()

    # Ensures that offset is set such that the current item
    # is visible.

    def adjust_offset(self, item):
        offset = self.callbacks["get_var"]("offset")

        if offset > item.max_offset:
            offset = min(item.max_offset, self.max_offset)
        elif offset < item.min_offset:
            offset = max(item.min_offset, 0)

        self.set_offset(offset)

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
        self.set_offset(offset)
        self._set_cursor(newsel)

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
        self.set_offset(offset)
        if newsel:
            self._set_cursor(newsel)

    @command_format([("item", "sel_or_item")])
    def cmd_reader(self, **kwargs):
        self.callbacks["set_var"]("reader_item", kwargs["item"])
        self.callbacks["set_var"]("reader_offset", 0)
        self.callbacks["add_window"](Reader)

    @command_format([("tags", "listof_tags")])
    def cmd_promote(self, **kwargs):
        for tag in kwargs["tags"]:

            log.debug("Promoting %s\n" % tag.tag)

            # Refetch because a promote call will cause our eval_tag hook to
            # recreate visible_tags.

            visible_tags = self.callbacks["get_var"]("taglist_visible_tags")

            curidx = visible_tags.index(tag)

            # Obviously makes no sense on top tag.
            if curidx == 0:
                return

            # Re-order tags and update internal list order.
            self.callbacks["promote_tag"](tag, visible_tags[curidx - 1])

    @command_format([("tags", "listof_tags")])
    def cmd_demote(self, **kwargs):
        pass

    def update_tag_lists(self):
        self.tags = self.callbacks["get_var"]("curtags")
        hide_empty = self.callbacks["get_opt"]("taglist.hide_empty_tags")

        t = []
        cur_item_offset = 0

        for i, tag in enumerate(self.tags):
            if hide_empty and len(tag) == 0:
                continue

            # Update index info
            tag.set_item_offset(cur_item_offset)
            tag.set_tag_offset(i)
            tag.set_visible_tag_offset(len(t))

            cur_item_offset += len(tag)
            t.append(tag)

        if t and not self.first_obj:
            self.first_obj = t[0]
        elif not t and self.first_obj:
            self.first_obj = None

        self.callbacks["set_var"]("taglist_visible_tags", t)

    # Refresh updates information used to render the objects.
    # Effectively, we build a doubly linked list out of all
    # of the objects by setting obj.prev_obj and obj.next_obj.

    # This is so that set_offset() can start traversing
    # the list at the current first_obj and search immediately
    # in the direction of the next first_obj.

    # We also set obj.max_draw_offset which set_offset() uses
    # to identify when it has searched far enough. This identifier
    # is entirely about which object needs to be rendered first,
    # which is not necessarily the first visible object.

    # In addition we update scrolling info. obj.max_offset and
    # obj.min_offset are used for *visible* items so that
    # we a new selection is made, the offset can be set correctly
    # such that the entire item is visible.

    def refresh(self):
        self.update_tag_lists()

        prev_obj = None

        for tag in self.callbacks["get_var"]("taglist_visible_tags"):

            tag.prev_obj = prev_obj
            tag.next_obj = None

            if not prev_obj:
                tag.max_offset = 0
                tag.max_draw_offset = 0 + (tag.lines - 1)
                tag.min_offset = -1 * ((self.height - 1) - tag.lines)
            else:
                tag.max_offset = prev_obj.max_offset + prev_obj.lines
                tag.max_draw_offset = prev_obj.max_draw_offset + tag.lines 
                tag.min_offset = prev_obj.min_offset + tag.lines

                prev_obj.next_obj = tag

            prev_obj = tag

            for story in tag:
                story.prev_obj = prev_obj
                story.next_obj = None

                story.max_draw_offset = prev_obj.max_draw_offset + story.lines 
                story.min_offset = prev_obj.min_offset + story.lines

                # Adjust for floating header. We derive the max_offset from
                # max_draw_offset rather than prev_obj.max_draw_offset because
                # we don't want to adjust for tag.lines multiple times.

                story.max_offset = (prev_obj.max_draw_offset + 1) - tag.lines

                prev_obj.next_obj = story
                prev_obj = story

        # If we have less than a screenful of
        # content, set max_offset to pin it to the top.

        if prev_obj:
            self.max_offset = max(prev_obj.min_offset, 0)
        else:
            self.max_offset = 0

        # If we've got a selection make sure it's
        # still going to be onscreen.

        sel = self.callbacks["get_var"]("selected")
        if sel:
            self.adjust_offset(sel)

        self.redraw()

    # curpos - position in visible windown, can be negative
    # main_offset - starting line from top of pad

    def _partial_render(self, obj, main_offset, curpos):
        lines = obj.lines
        draw_lines = lines

        if curpos + lines > 0:
            start = 0

            # If we're crossing the boundary to onscreen
            # trim render window.
            if curpos < 0:
                start = -1 * curpos
                draw_lines += curpos

            # If we're crossing the boundary to offscreen
            # trim render window.
            if main_offset + draw_lines > self.height:
                draw_lines = self.height - main_offset

            if draw_lines:
                obj.pad.overwrite(self.pad, start, 0, main_offset, 0,
                        main_offset + (draw_lines - 1), self.width - 2)
                return (main_offset + draw_lines, curpos + lines)

        return (main_offset, curpos + lines)

    def redraw(self):
        self.pad.erase()

        offset = self.callbacks["get_var"]("offset")
        w_offset = 0

        obj = self.first_obj

        if not obj:
            self.pad.addstr("All tags empty.")
            self.callbacks["refresh"]()
            return

        # Calculate the offset into the current item. For example,
        # if offset is 1, and the first item starts at 0 but ends on
        # line 1, then the first line rendered will be the second line
        # of the first item, so curpos = -1 (discard the one line).

        # At first blush, this feels like it should be a simpler
        # formulate like `offset - obj.max_offset` but you have to
        # remember that max_offset is for setting the offset when
        # scrolling and it takes into account the floating header.
        # Therefore, we have to derive it from max_draw_offset which
        # is the maximum offset that the item should be the first to
        # render.

        curpos = -1 * ((obj.lines - 1) - (obj.max_draw_offset - offset))

        rendered_header = False

        while obj:
            # Save offset, curpos in case we need to overwrite.
            w, c = w_offset, curpos

            # Copy item into window
            w_offset, curpos = self._partial_render(obj, w_offset, curpos)

            # Render floating header, if we've covered enough ground.

            if not rendered_header and curpos > 0:
                if obj in self.tags:
                    tag = obj
                else:
                    tag = self.tag_by_item(obj)

                if curpos >= tag.lines:
                    self._partial_render(tag, 0, 0)
                    rendered_header = True

            if w_offset >= self.height:
                break

            obj = obj.next_obj

        self.callbacks["refresh"]()

    def is_input(self):
        return False

    def get_opt_name(self):
        return "taglist"

    def get_height(self, mheight):
        return mheight

    def get_width(self, mwidth):
        return mwidth
