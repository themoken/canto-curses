# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.hooks import on_hook, remove_hook
from canto_next.plugins import Plugin

from .tagcore import tag_updater
from .guibase import GuiBase
from .reader import Reader

import logging
import curses
import os
import re

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
        self.update_plugin_lookups()

    def init(self, pad, callbacks):
        # Drawing information
        self.pad = pad
        self.height, self.width = self.pad.getmaxyx()

        # Callback information
        self.callbacks = callbacks

        # Holster for a list of items for batch operations.
        self.got_items = None

        self.first_sel = None

        self.first_story = None
        self.last_story = None

        self.tags = []

        # Hooks
        on_hook("curses_eval_tags_changed", self.on_eval_tags_changed)
        on_hook("curses_stories_added", self.on_stories_added)
        on_hook("curses_stories_removed", self.on_stories_removed)
        on_hook("curses_opt_change", self.on_opt_change)

        self.update_tag_lists()

    def die(self):
        log.debug("Cleaning up hooks...")
        remove_hook("curses_eval_tags_changed", self.on_eval_tags_changed)
        remove_hook("curses_stories_added", self.on_stories_added)
        remove_hook("curses_stories_removed", self.on_stories_removed)
        remove_hook("curses_opt_change", self.on_opt_change)

    def item_by_idx(self, idx):
        if idx < 0:
            raise Exception("Negative indices not allowed!")

        cur = self.first_story
        while cur:
            log.debug("cur.offset = %s" % cur.offset)
            if cur.offset == idx:
                return cur
            cur = cur.next_story

        raise Exception("Couldn't find item with idx: %d" % idx)

    def tag_by_item(self, item):
        for tag in self.tags:
            if item in tag:
                return tag
        raise Exception("Couldn't find tag of item: %s" % item)

    def tag_by_obj(self, obj):
        if obj in self.tags:
            return obj
        return self.tag_by_item(obj)

    def on_eval_tags_changed(self):
        self.callbacks["set_var"]("needs_refresh", True)

    # Called with sync_lock, so we are unrestricted.

    def on_stories_added(self, tag, items):
        # Items being added implies we need to remap them
        self.callbacks["set_var"]("needs_refresh", True)

        # The rest of this function is about trying to
        # maintain the selection.

        sel = self.callbacks["get_var"]("selected")
        if sel:
            return

        old_sel = self.callbacks["get_var"]("old_selected")

        if not old_sel or\
                old_sel in self.tags or\
                old_sel not in items:
            return

        # Re-reference. The stories equality is based
        # entirely on its ID value, but we still need
        # to make sure we have the new item.

        new_sel = items[items.index(old_sel)]
        new_sel.select()

        # Retain cursor and attempt to keep it at the
        # same place on screen.

        old_toffset = self.callbacks["get_var"]("old_toffset")

        self._set_cursor(new_sel, old_toffset)

        self.callbacks["set_var"]("old_selected", None)

    # Called with sync_lock, so we are unrestricted.

    def on_stories_removed(self, tag, items):
        # Items being removed implies we need to remap them.
        self.callbacks["set_var"]("needs_refresh", True)

        # We need to clear self.first_sel if it's gone
        # so that a potential unselect doesn't try and set
        # it as the redraw target object.

        if self.first_sel and\
                self.first_sel not in self.tags and\
                self.first_sel in items:
            self.first_sel = None

        sel = self.callbacks["get_var"]("selected")
        if sel and sel not in self.tags and sel in items:
            toffset = self.callbacks["get_var"]("target_offset")
            self._set_cursor(None, 0)

            self.callbacks["set_var"]("old_selected", sel)
            self.callbacks["set_var"]("old_toffset", toffset)

    def on_opt_change(self, conf):
        if "taglist" not in conf or "search_attributes" not in conf["taglist"]:
            return

        log.info("Fetching any needed search attributes")

        need_attrs = {}
        sa = self.callbacks["get_opt"]("taglist.search_attributes")

        # Make sure that we have all attributes needed for a search.
        for tag in self.callbacks["get_var"]("alltags"):
            for item in tag:
                tag_updater.need_attributes(item.id, sa)

    def cmd_goto(self, **kwargs):
        self._goto([item.content["link"] for item in kwargs["items"]])

    def cmd_tag_state(self, **kwargs):
        attributes = {}
        for tag in kwargs["tags"]:
            for item in tag:
                if item.handle_state(kwargs["state"]):
                    attributes[item.id] = { "canto-state" : kwargs["state"] }

        if attributes:
            tag_updater.set_attributes(attributes)

    # item-state: Add/remove state for multiple items.

    def cmd_item_state(self, **kwargs):
        attributes = {}
        for item in kwargs["items"]:
            if item.handle_state(kwargs["state"]):
                attributes[item.id] = { "canto-state" : item.content["canto-state"] }

        if attributes:
            tag_updater.set_attributes(attributes)

    def cmd_unset_cursor(self, **kwargs):
        self._set_cursor(None, 0)

    def _iterate_forward(self, start):
        ns = start.next_sel
        o = start

        lines = 0

        # No next item, bail.

        if not ns:
            return (None, lines)

        # Force changes to all objects between
        # start and next sel.

        while o and o != ns:
            o.do_changes(self.width)
            lines += o.lines + o.extra_lines
            o = o.next_obj

        return (ns, lines)

    def _iterate_backward(self, start):
        ps = start.prev_sel
        o = start

        lines = 0

        # No prev item, bail.

        if not ps:
            return (None, lines)

        # Force changes to all objects between
        # start and prev sel.

        while o and o != ps:
            o = o.prev_obj
            o.do_changes(self.width)
            lines += o.lines + o.extra_lines

        return (ps, lines)

    def cmd_rel_set_cursor(self, **kwargs):
        sel = self.callbacks["get_var"]("selected")
        if sel:
            target_idx = sel.sel_offset + kwargs["relidx"]
            curpos = sel.curpos

            if target_idx < 0:
                target_idx = 0

            while sel.sel_offset != target_idx:
                if target_idx < sel.sel_offset and sel.prev_sel:
                    sel, lines = self._iterate_backward(sel)
                    curpos -= lines
                elif target_idx > sel.sel_offset and sel.next_sel:
                    sel, lines = self._iterate_forward(sel)
                    curpos += lines
                else:
                    break
            self._set_cursor(sel, curpos)
        else:
            self._set_cursor(self.first_sel, 0)

    def _set_cursor(self, item, window_location):
        # May end up as None
        sel = self.callbacks["get_var"]("selected")

        if sel:
            sel.unselect()

        self.callbacks["set_var"]("selected", item)

        if item:

            conf = self.callbacks["get_conf"]()
            curstyle = conf["taglist"]["cursor"]

            # Convert window position for absolute positioning, edge
            # positioning uses given window_location.

            if curstyle["type"] == "top":
                window_location = 0
            elif curstyle["type"] == "middle":
                window_location = int((self.height - 1) / 2)
            elif curstyle["type"] == "bottom":
                window_location = self.height - 1

            # If the tag header is larger than the edge, the scroll will never
            # be triggered (redraw resets screen position to keep items visible
            # despite the tag header).

            if item in self.tags:
                tag = item
            else:
                tag = self.tag_by_item(item)

            tag.do_changes(self.width)
            wl_top = max(curstyle["edge"], tag.lines)

            # Similarly, if the current item is larger than the (edge + 1), the
            # scroll won't be triggered, so we take the max edge there too.

            item.do_changes(self.width)
            wl_bottom = (self.height - 1) - max(curstyle["edge"], item.lines)

            if window_location > wl_bottom:
                if curstyle["scroll"] == "scroll":
                    window_location = wl_bottom
                elif curstyle["scroll"] == "page":
                    window_location = wl_top
            elif window_location < wl_top:
                if curstyle["scroll"] == "scroll":
                    window_location = wl_top
                elif curstyle["scroll"] == "page":
                    window_location = wl_bottom

            self.callbacks["set_var"]("target_obj", item)
            self.callbacks["set_var"]("target_offset", window_location)
            item.select()
        else:
            self.callbacks["set_var"]("target_obj", self.first_sel)
            if self.first_sel:
                self.callbacks["set_var"]("target_offset", self.first_sel.curpos)

    # foritems gets a valid list of items by index.

    def cmd_foritems(self, **kwargs):
        self.got_items = kwargs["items"]

    def cmd_foritem(self, **kwargs):
        log.debug("setting got_items: %s" % [ kwargs["item"] ])
        self.got_items = [ kwargs["item"] ]

    # clearitems clears all the items set by foritems.

    def cmd_clearitems(self, **kwargs):
        self.got_items = None

    def cmd_page_up(self, **kwargs):
        target_offset = self.callbacks["get_var"]("target_offset")
        target_obj = self.callbacks["get_var"]("target_obj")
        sel = self.callbacks["get_var"]("selected")

        # No items, forget about it
        if not target_obj:
            return

        scroll = self.height - 1

        if sel:
            while scroll > 0 and sel.prev_sel:
                pstory = sel.prev_sel
                while sel != pstory:
                    sel.do_changes(self.width)
                    scroll -= sel.lines
                    sel = sel.prev_obj

            self._set_cursor(sel, target_offset)
        else:
            while scroll > 0 and target_obj.prev_obj:
                target_obj = target_obj.prev_obj

                target_obj.do_changes(self.width)
                scroll -= target_obj.lines

            self.callbacks["set_var"]("target_obj", target_obj)
            self.callbacks["set_var"]("target_offset", target_offset)
            self.callbacks["set_var"]("needs_redraw", True)

    def cmd_page_down(self, **kwargs):
        target_offset = self.callbacks["get_var"]("target_offset")
        target_obj = self.callbacks["get_var"]("target_obj")
        sel = self.callbacks["get_var"]("selected")

        # No items, forget about it.
        if not target_obj:
            return

        scroll = self.height - 1

        if sel:
            while scroll > 0 and sel.next_sel:
                sel.do_changes(self.width)
                if scroll < sel.lines:
                    break

                nstory = sel.next_sel
                while sel != nstory:
                    sel.do_changes(self.width)
                    scroll -= sel.lines
                    sel = sel.next_obj

            self._set_cursor(sel, target_offset)
        else:
            while scroll > 0 and target_obj.next_obj:
                target_obj.do_changes(self.width)
                scroll -= target_obj.lines
                if scroll < 0:
                    break
                target_obj = target_obj.next_obj

            self.callbacks["set_var"]("target_obj", target_obj)
            self.callbacks["set_var"]("target_offset", 0)
            self.callbacks["set_var"]("needs_redraw", True)

    def cmd_next_tag(self, **kwargs):
        sel = self.callbacks["get_var"]("selected")

        if not sel:
            return self._set_cursor(self.first_sel, 0)

        target_offset = self.callbacks["get_var"]("target_offset")

        if sel not in self.tags:
            tag = self.tag_by_item(sel)
        else:
            tag = sel

        while sel.next_sel:
            sel = sel.next_sel

            # This will be true for stories as well as selectable tags
            if sel not in tag:
                break

        self._set_cursor(sel, target_offset)

    def cmd_prev_tag(self, **kwargs):
        sel = self.callbacks["get_var"]("selected")

        if not sel:
            return self._set_cursor(self.first_sel, 0)

        target_offset = self.callbacks["get_var"]("target_offset")

        if sel not in self.tags:
            tag = self.tag_by_item(sel)
        else:
            tag = sel

        while sel.prev_sel:
            sel = sel.prev_sel

            if sel not in self.tags:
                newtag = self.tag_by_item(sel)
                if newtag != tag:

                    # If the current cursor is an item, in a newtag, we know
                    # the tag's next_obj is the first story, which may also be
                    # this item.

                    sel = newtag.next_obj
                    break
            else:
                if sel != tag:
                    break

        self._set_cursor(sel, target_offset)

    def cmd_reader(self, **kwargs):
        self.callbacks["set_var"]("reader_item", kwargs["item"])
        self.callbacks["set_var"]("reader_offset", 0)
        self.callbacks["add_window"](Reader)

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
            self.callbacks["switch_tags"](tag, visible_tags[curidx - 1])

    def cmd_demote(self, **kwargs):
        for tag in kwargs["tags"]:

            log.debug("Demoting %s\n", tag.tag)

            visible_tags = self.callbacks["get_var"]("taglist_visible_tags")

            # Obviously makes no sense on bottom or only tag.
            if tag == visible_tags[-1] or len(visible_tags) == 1:
                return

            curidx = visible_tags.index(tag)
            self.callbacks["switch_tags"](tag, visible_tags[curidx + 1])

    def _collapse_tag(self, tag):
        log.debug("Collapsing %s\n", tag.tag)

        # If we're collapsing the selection, select
        # the tag instead.
        s = self.callbacks["get_var"]("selected")
        if s and s in tag:
            toffset = self.callbacks["get_var"]("target_offset")
            self._set_cursor(tag, toffset) 

        self.callbacks["set_tag_opt"](tag, "collapsed", True)

    def cmd_collapse(self, **kwargs):
        for tag in kwargs["tags"]:
            self._collapse_tag(tag)

    def _uncollapse_tag(self, tag):
        log.debug("Uncollapsing %s\n", tag.tag)

        # If we're uncollapsing the selected tag,
        # go ahead and select the first item.

        s = self.callbacks["get_var"]("selected")
        if s and tag == s and len(tag) != 0:
            toffset = self.callbacks["get_var"]("target_offset") + tag.lines
            self._set_cursor(tag[0], toffset)

        self.callbacks["set_tag_opt"](tag, "collapsed", False)

    def cmd_uncollapse(self, **kwargs):
        for tag in kwargs["tags"]:
            self._uncollapse_tag(tag)

    def cmd_toggle_collapse(self, **kwargs):
        for tag in kwargs["tags"]:
            if self.callbacks["get_tag_opt"](tag, "collapsed"):
                self._uncollapse_tag(tag)
            else:
                self._collapse_tag(tag)

    def search(self, regex):
        try:
            rgx = re.compile(regex)
        except Exception as e:
            self.callbacks["set_var"]("error_msg", e)
            return

        story = self.first_story
        terms = self.callbacks["get_opt"]("taglist.search_attributes")

        while story:
            for t in terms:

                # Shouldn't happen unless a search happens before
                # the daemon can respond to the ATTRIBUTES request.

                if t not in story.content:
                    continue

                if rgx.match(story.content[t]):
                    story.mark()
                    break
            else:
                story.unmark()

            story = story.next_story

        self.callbacks["set_var"]("needs_redraw", True)

    def cmd_search(self, **kwargs):
        if not kwargs["search_term"]:
            return
        rgx = ".*" + re.escape(kwargs["search_term"]) + ".*"
        return self.search(rgx)

    def cmd_search_regex(self, **kwargs):
        if not kwargs["search_term"]:
            return
        return self.search(kwargs["search_term"])

    def cmd_next_marked(self, **kwargs):
        start = self.callbacks["get_var"]("selected")

        # This works for tags and stories alike.
        if start:
            cur = start.next_story
        else:
            start = self.first_story
            cur = start

        # There's nothing to search
        if not cur:
            return

        curpos = cur.curpos

        while not cur or not cur.marked:
            # Wrap to top
            if cur == None:
                cur = self.first_story
                curpos = self.first_story.curpos
            else:
                cur, lines = self._iterate_forward(cur)
                curpos += lines

            # Make sure we don't infinite loop.
            if cur == start:
                if not cur.marked:
                    self.callbacks["set_var"]\
                            ("info_msg", "No marked items.")
                break

        self._set_cursor(cur, curpos)

    def cmd_prev_marked(self, **kwargs):
        start = self.callbacks["get_var"]("selected")

        # This works for tags and stories alike.
        if start:
            cur = start.prev_story
        else:
            start = self.last_story
            cur = start

        # There's nothing to search
        if not cur:
            return

        curpos = cur.curpos

        while not cur or not cur.marked:
            # Wrap to bottom
            if cur == None:
                cur = self.last_story
                curpos = self.last_story.curpos
            else:
                cur, lines = self._iterate_backward(cur)
                curpos -= lines

            # Make sure we don't infinite loop.
            if cur == start:
                self.callbacks["set_var"]("info_msg", "No marked items.")
                break

        self._set_cursor(cur, curpos)

    def cmd_tag_config(self, **kwargs):
        tag = kwargs["tag"].tag.replace(".","\\.")
        config = kwargs["config"]

        argv = ["canto-remote", "one-config", "tags." + tag + "." + config]
        self._remote_argv(argv)

    def cmd_add_tag(self, **kwargs):
        for tag in kwargs["tags"]:
            tc = self.callbacks["get_tag_conf"](tag)
            extratag = kwargs["extratag"]

            if extratag not in tc["extra_tags"]:
                tc["extra_tags"].append(extratag)

            self.callbacks["set_tag_conf"](tag, tc)

    def cmd_del_tag(self, **kwargs):
        for tag in kwargs["tags"]:
            tc = self.callbacks["get_tag_conf"](tag)
            extratag = kwargs["extratag"]

            if extratag in tc["extra_tags"]:
                tc["extra_tags"].remove(extratag)

            self.callbacks["set_tag_conf"](tag, tc)

    def update_tag_lists(self):
        sel = self.callbacks["get_var"]("selected")
        toffset = self.callbacks["get_var"]("target_offset")

        # We unset selection selection because we're unsure that the selection
        # will still be visible, and we needn't have gotten an
        # on_items_removed call.

        # We may restore the selection later, if possible.

        self.first_sel = None
        self._set_cursor(None, 0)

        # Determine if our selection is a tag.
        # If it is, and it is no longer visible,
        # then we have to unset the selection.

        sel_is_tag = False
        if self.tags and sel and sel in self.tags:
            sel_is_tag = True

        self.tags = self.callbacks["get_var"]("curtags")
        hide_empty = self.callbacks["get_opt"]("taglist.hide_empty_tags")

        cur_item_offset = 0
        cur_sel_offset = 0
        t = []

        for i, tag in enumerate(self.tags):
            if hide_empty and len(tag) == 0:
                continue

            # Update index info
            tag.set_item_offset(cur_item_offset)
            tag.set_sel_offset(cur_sel_offset)
            tag.set_tag_offset(i)
            tag.set_visible_tag_offset(len(t))

            if self.callbacks["get_tag_opt"](tag.tag, "collapsed"):
                cur_sel_offset += 1
            else:
                cur_sel_offset += len(tag)
                cur_item_offset += len(tag)

            # Maintain item selection
            if sel in tag:
                newsel = tag[tag.index(sel)]
                self._set_cursor(newsel, toffset)

            t.append(tag)

        # Restore selected tag, if it exists

        if sel_is_tag and sel in t:
            self._set_cursor(sel, toffset)

        self.callbacks["set_var"]("taglist_visible_tags", t)

    def update_target_obj(self):
        # Set initial target_obj if none already set, or if it's stale.

        target_obj = self.callbacks["get_var"]("target_obj")
        vistags = self.callbacks["get_var"]("taglist_visible_tags")

        if vistags:
            if not target_obj:
                self.callbacks["set_var"]("target_obj", vistags[0])
                self.callbacks["set_var"]("target_offset", 0)
            else:
                try:
                    tag = self.tag_by_item(target_obj)
                except Exception as e:
                    if target_obj not in vistags:
                        # Not a story in tags and not a tag? Reset.
                        self.callbacks["set_var"]("target_obj", vistags[0])
                        self.callbacks["set_var"]("target_offset", 0)
        else:
            self.callbacks["set_var"]("target_obj", None)
            self.callbacks["set_var"]("target_offset", 0)

    # Refresh updates information used to render the objects.
    # Effectively, we build a doubly linked list out of all
    # of the objects by setting obj.prev_obj and obj.next_obj.

    def refresh(self):

        log.debug("Taglist REFRESH!\n")

        self.update_tag_lists()
        self.update_target_obj()

        self.first_story = None

        prev_obj = None
        prev_story = None
        prev_sel = None

        for tag in self.callbacks["get_var"]("taglist_visible_tags"):
            tag.prev_obj = prev_obj
            tag.next_obj = None

            tag.prev_story = prev_story
            tag.next_story = None

            tag.prev_sel = prev_sel
            tag.next_sel = None

            if prev_obj != None:
                prev_obj.next_obj = tag

            prev_obj = tag

            # Collapsed tags (with items) skip stories.
            if self.callbacks["get_tag_opt"](tag.tag, "collapsed"):
                if prev_sel:
                    prev_sel.next_sel = tag
                prev_sel = tag
                continue

            for story in tag:
                if not self.first_story:
                    self.first_story = story

                story.prev_obj = prev_obj
                story.next_obj = None
                prev_obj.next_obj = story
                prev_obj = story

                if prev_story != None:
                    prev_story.next_story = story
                story.prev_story = prev_story
                story.next_story = None
                prev_story = story

                # We want next_story to be accessible from all objects, so head
                # back and set it for any without one, even if it wasn't the
                # last story object (i.e. if it's a tag)

                cur = story.prev_obj
                while cur and cur.next_story == None:
                    cur.next_story = story
                    cur = cur.prev_obj

                if prev_sel != None:
                    prev_sel.next_sel = story
                story.prev_sel = prev_sel
                story.next_sel = None
                prev_sel = story

                # Keep track of last story.
                self.last_story = story

        self.callbacks["set_var"]("needs_redraw", True)

    # curpos - position in visible windown, can be negative
    # main_offset - starting line from top of pad

    def _partial_render(self, obj, main_offset, curpos, footer = False):
        if not footer:
            lines = obj.lines
            pad = obj.pad
        else:
            lines = obj.footlines
            pad = obj.footpad

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
                pad.overwrite(self.pad, start, 0, main_offset, 0,
                        main_offset + (draw_lines - 1), self.width - 1)
                return (main_offset + draw_lines, curpos + lines)

        return (main_offset, curpos + lines)

    def redraw(self):
        log.debug("Taglist REDRAW (%s)!\n" % self.width)
        self.pad.erase()

        target_obj = self.callbacks["get_var"]("target_obj")
        target_offset = self.callbacks["get_var"]("target_offset")

        # Bail if we have no item.

        if target_obj == None:
            self.pad.addstr("All tags empty.")
            self.callbacks["refresh"]()
            return

        # Step 0. Bounding. Make sure we're trying to render the
        # item to a place it's visible.

        # If we're trying to render the target_obj to a screen
        # position less then the length of it's tag header, then
        # we'd overwrite on writing the floating header, so adjust
        # the target_offset.

        if target_obj not in self.tags:
            tag = self.tag_by_item(target_obj)
            tag.do_changes(self.width)
            if target_offset < tag.lines:
                target_offset = tag.lines
        elif target_offset < 0:
            target_offset = 0

        # If we're trying to render too close to the bottom, we also
        # need an adjustment.

        target_obj.do_changes(self.width)
        if target_offset > ((self.height - 1) - target_obj.lines):
            target_offset = (self.height - 1) - target_obj.lines

        # Step 1. Find first object based on target_obj and target_offset,
        # This will cause any changes to be resolved for objects on screen
        # before and including the target object.

        obj = target_obj
        curpos = target_offset
        top_adjusted = False

        while curpos > 0:
            if obj.prev_obj:
                obj.prev_obj.do_changes(self.width)
                curpos -= (obj.prev_obj.lines + obj.prev_obj.extra_lines)
                obj = obj.prev_obj

            # If there aren't enough items to render before this item and
            # get to the top, adjust offset
            else:
                top_adjusted = True
                target_offset -= curpos
                curpos = 0

        # Step 2. Adjust offset, if necessary, to keep blank space from
        # the bottom of the list. This also causes any changes to be resolved
        # for objects on screen after the target object.

        last_obj = target_obj
        last_off = target_offset

        while last_off < (self.height - 1):
            if last_obj:
                last_obj.do_changes(self.width)
                last_off += last_obj.lines
                last_obj = last_obj.next_obj

            # Not enough items to render after our item,
            # adjust offset. Unfortunately, this means that
            # we need to refigure out everything above, so
            # we recurse, but as long as we haven't top_adjusted
            # we should only ever have a single level of
            # recursion and none of the refresh work we've done
            # at this level has been wasted.

            elif not top_adjusted:
                rem = (self.height - 1) - last_off
                self.callbacks["set_var"]("target_offset", target_offset + rem)
                self.redraw()
                return
            else:
                break

        # Any adjustments should be reflected.
        self.callbacks["set_var"]("target_offset", target_offset)

        # Step 3. Update self.first_sel. This is useful for making
        # initial selection based on the current screen position.
        # If there are only tags on screen, first_sel could be None

        self.first_sel = obj
        while self.first_sel in self.tags:

            if self.callbacks["get_tag_opt"](obj.tag, "collapsed"):
                break

            # We use obj instead of sel here because next_sel will only be set
            # if the current object is selectable, which it isn't if it's not
            # collapsed.

            if self.first_sel.next_obj:
                self.first_sel = self.first_sel.next_obj
            else:
                break

        # Step 4. Render.

        rendered_header = False
        w_offset = 0

        while obj != None:
            # Refresh if necessary, update curpos for scrolling.
            obj.do_changes(self.width)
            obj.curpos = curpos

            # Copy item into window
            w_offset, curpos = self._partial_render(obj, w_offset, curpos)

            # If we're at the end of a list, or the next item is a tag we need
            # to render the tag footer for the current tag.

            # Render floating header, if we've covered enough ground.

            if not rendered_header and curpos > 0:
                tag = self.tag_by_obj(obj)
                tag.do_changes(self.width)

                if curpos >= tag.lines:
                    self._partial_render(tag, 0, 0)
                    rendered_header = True

            # Do this before the floating header so that if no items are going
            # to be visible, the header is still displayed without the close.

            obj.extra_lines = 0

            if not obj.next_obj or obj.next_obj in self.tags:
                if obj in self.tags:
                    tag = obj
                else:
                    tag = self.tag_by_item(obj)
                    tag.do_changes(self.width)
                    obj.extra_lines = tag.footlines

                w_offset, curpos = self._partial_render(tag, w_offset, curpos, True)

                # Set this because if we don't have room above the footer for
                # the header (implied by this block executing with
                # rendered_header == False), then actually rendering one looks
                # broken.

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
