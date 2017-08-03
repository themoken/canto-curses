# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2016 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.hooks import on_hook, remove_hook, unhook_all
from canto_next.plugins import Plugin

from .command import register_commands, register_arg_types, unregister_all, _int_range, _int_check, _string
from .tagcore import tag_updater, alltagcores
from .locks import config_lock
from .guibase import GuiBase
from .reader import Reader
from .tag import Tag, alltags

import logging
import curses
import shlex
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
    def init(self, pad, callbacks):
        GuiBase.init(self)

        # Drawing information
        self.pad = pad
        self.height, self.width = self.pad.getmaxyx()

        # Callback information
        self.callbacks = callbacks

        # Holster for a list of items for batch operations.
        self.got_items = []

        self.first_sel = None

        self.first_story = None
        self.last_story = None

        self.tags = []
        self.spacing = callbacks["get_opt"]("taglist.spacing")

        # Hold config log so we don't miss any new TagCores or get updates
        # before we're ready.

        on_hook("curses_eval_tags_changed", self.on_eval_tags_changed, self)
        on_hook("curses_items_added", self.on_items_added, self)
        on_hook("curses_items_removed", self.on_items_removed, self)
        on_hook("curses_tag_updated", self.on_tag_updated, self)
        on_hook("curses_stories_added", self.on_stories_added, self)
        on_hook("curses_stories_removed", self.on_stories_removed, self)
        on_hook("curses_opt_change", self.on_opt_change, self)
        on_hook("curses_new_tagcore", self.on_new_tagcore, self)
        on_hook("curses_del_tagcore", self.on_del_tagcore, self)

        args = {
            "cursor-offset": ("[cursor-offset]", self.type_cursor_offset),
            "item-list": ("[item-list]: List of item indices (tab complete to show)\n  Simple: 1,3,6,5\n  Ranges: 1-100\n  All: *\n  Selected item: .\n  Domains tag,1,2,3 for 1,2,3 of current tag", self.type_item_list, self.hook_item_list),
            "item-state": ("[item-state]: Any word, can be inverted with minus ex: '-read' or 'marked'", self.type_item_state),
            "tag-list": ("[tag-list]: List of tag indices (tab complete to show)\n  Simple: 1,3,6,5\n  Ranges: 1-100\n  Selected tag: .\n  All: *", self.type_tag_list, self.hook_tag_list),
            # string because tag-item will manually bash in user: prefix
            "user-tag" : ("[user-tag]: Any string, like 'favorite', or 'cool'", self.type_user_tag),
            "category" : ("[category]: Any string, like 'news' or 'comics'", self.type_category),
        }

        base_cmds = {
            "remote delfeed" : (self.cmd_delfeed, ["tag-list"], "Unsubscribe from feeds."),
        }

        nav_cmds = {
            "page-down": (self.cmd_page_down, [], "Move down a page of items"),
            "page-up": (self.cmd_page_up, [], "Move up a page of items"),
            "next-tag" : (self.cmd_next_tag, [], "Scroll to next tag"),
            "prev-tag" : (self.cmd_prev_tag, [], "Scroll to previous tag"),
            "next-marked" : (self.cmd_next_marked, [], "Scroll to next marked item"),
            "prev-marked" : (self.cmd_prev_marked, [], "Scroll to previous marked item"),
            "rel-set-cursor 1": (lambda : self.cmd_rel_set_cursor(1), [], "Next item"),
            "rel-set-cursor -1": (lambda : self.cmd_rel_set_cursor(-1), [], "Previous item"),
        }

        hidden_cmds = {
            "rel-set-cursor": (self.cmd_rel_set_cursor, ["cursor-offset"], "Move the cursor by cursor-offset items"),
        }

        grouping_cmds = {
            "foritems": (self.cmd_foritems, ["item-list"], "Collect items for future commands\n\nAfter a foritems call, subsequent commands that take [item-lists] will use them.\n\nCan be cleared with clearitems."),
            "foritem": (self.cmd_foritem, ["item-list"], "Collect first item for future commands\n\nAfter a foritem call, subsequent commands that take [item-lists] will use the first item given.\n\nCan be cleared with clearitems."),
            "clearitems": (self.cmd_clearitems, [], "Clear collected items (see foritem / foritems)"),
        }

        item_cmds = {
            "goto": (self.cmd_goto, ["item-list"], "Open story links in browser"),
            "reader": (self.cmd_reader, ["item-list"], "Open the built-in reader"),
            "tag-item" : (self.cmd_tag_item, ["user-tag", "item-list"], "Add a tag to individual items"),
            "tags": (self.cmd_tags, ["item-list"], "Show tag of selected items"),
            "item-state": (self.cmd_item_state, ["item-state", "item-list"], "Set item state (i.e. 'item-state read .')"),
            "tag-state": (self.cmd_tag_state, ["item-state", "tag-list"], "Set item state for all items in tag (i.e. 'tag-state read .')"),
        }

        collapse_cmds = {
            "collapse" : (self.cmd_collapse, ["tag-list"], "Collapse tags - reduce the tag's output to a simple status line."),
            "uncollapse" : (self.cmd_uncollapse, ["tag-list"], "Uncollapse tags - show the full content of a tag"),
            "toggle-collapse" : (self.cmd_toggle_collapse, ["tag-list"], "Toggle collapsed state of tags."),
        }


        search_cmds = {
            "search" : (self.cmd_search, ["string"], "Search items for string"),
            "search-regex" : (self.cmd_search_regex, ["string"], "Search items for regex"),
        }

        tag_cmds = {
            "promote" : (self.cmd_promote, ["tag-list"], "Move tags up in the display order (opposite of demote)"),
            "demote" : (self.cmd_demote, ["tag-list"], "Move tags down in the display order (opposite of promote)"),
        }

        tag_group_cmds = {
            "categorize" : (self.cmd_categorize, ["category", "tag-list"], "Categorize a tag"),
            "remove-category" : (self.cmd_remove_category, ["category", "tag-list"], "Remove a tag from a category"),
            "categories" : (self.cmd_categories, ["tag-list"], "Query what categories a tag is in."),
            "show-category" : (self.cmd_show_category, ["category"], "Show only tags in category."),
        }

        register_commands(self, base_cmds, "Base")
        register_commands(self, nav_cmds, "Navigation")
        register_commands(self, hidden_cmds, "hidden")
        register_commands(self, grouping_cmds, "Grouping")
        register_commands(self, item_cmds, "Item")
        register_commands(self, collapse_cmds, "Collapse")
        register_commands(self, search_cmds, "Search")
        register_commands(self, tag_cmds, "Tag")
        register_commands(self, tag_group_cmds, "Tag Grouping")

        register_arg_types(self, args)

        self.plugin_class = TagListPlugin
        self.update_plugin_lookups()

    def die(self):
        log.debug("Cleaning up hooks...")
        unhook_all(self)
        unregister_all(self)

    def tag_by_item(self, item):
        return item.parent_tag

    def tag_by_obj(self, obj):
        if obj.is_tag:
            return obj
        return obj.parent_tag

    # Types return (completion generator, validator)

    # None completions indicates that the help text should be enough (which
    # happens if it's a generic type without bounds)

    def type_cursor_offset(self):
        return (None, _int_check)

    def unhook_item_list(self, vars):
        # Perhaps this should be a separate hook for command completion?
        if "input_prompt" in vars:
            self.callbacks["set_opt"]("story.enumerated", False)
            self.callbacks["release_gui"]()
            remove_hook("curses_var_change", self.unhook_item_list)

    def hook_item_list(self):
        if not self.callbacks["get_opt"]("story.enumerated"):
            self.callbacks["set_opt"]("story.enumerated", True)
            self.callbacks["release_gui"]()
            on_hook("curses_var_change", self.unhook_item_list, self)

    def type_item_list(self):
        all_items = []
        for tag in self.tags:
            if tag.collapsed:
                continue
            for s in tag:
                all_items.append(s)

        domains = { 'all' : all_items }

        syms = { 'all' : {} }
        sel = self.callbacks["get_var"]("selected")

        if sel:
            # If we have a selection, we have a sensible tag domain

            tag = self.tag_by_obj(sel)
            domains['tag']  = [ x for x in tag ]
            syms['tag'] = {}

            if not sel.is_tag:
                syms['tag']['.'] = [ domains['tag'].index(sel) ]
                syms['tag']['*'] = range(0, len(domains['tag']))
                syms['all']['.'] = [ all_items.index(sel) ]
            elif len(sel) > 0:
                syms['tag']['.'] = [ 0 ]
                syms['tag']['*'] = range(0, len(sel))
            else:
                syms['tag']['.'] = []
                syms['tag']['*'] = []
        else:
            syms['all']['.'] = [ ]

        syms['all']['*'] = range(0, len(all_items))

        # if we have items, pass them in, otherwise pass in selected which is the implied context

        fallback = self.got_items[:]
        if fallback == [] and sel and not sel.is_tag:
            fallback = [ sel ]

        return (None, lambda x: _int_range("item", domains, syms, fallback, x))

    def unhook_tag_list(self, vars):
        # Perhaps this should be a separate hook for command completion?
        if "input_prompt" in vars:
            self.callbacks["set_opt"]("taglist.tags_enumerated", False)
            self.callbacks["release_gui"]()
            remove_hook("curses_var_change", self.unhook_tag_list)

    def hook_tag_list(self):
        if not self.callbacks["get_opt"]("taglist.tags_enumerated"):
            self.callbacks["set_opt"]("taglist.tags_enumerated", True)
            self.callbacks["release_gui"]()
            on_hook("curses_var_change", self.unhook_tag_list, self)

    def type_tag_list(self):
        vtags = self.callbacks["get_var"]("taglist_visible_tags")

        domains = { 'all' : vtags }
        syms = { 'all' : {} }

        sel = self.callbacks["get_var"]("selected")

        deftags = []
        if sel and sel.is_tag:
            deftags = [ sel ]
            syms['all']['.'] = [ vtags.index(sel) ]
        elif sel:
            deftags = [ self.tag_by_item(sel) ]
            syms['all']['.'] = [ vtags.index(deftags[0]) ]
        else:
            syms['all']['.'] = [ ]

        syms['all']['*'] = range(0, len(vtags))

        for i, tag in enumerate(vtags):
            if tag.tag.startswith("maintag:"):
                syms['all'][tag.tag[8:]] = [ i ]

        return (None, lambda x: _int_range("tag", domains, syms, deftags, x))

    # This will accept any state, but should offer some completions for sensible ones

    def type_item_state(self):
        return (["read","marked","-read","-marked"], lambda x : (True, x))

    def on_new_tagcore(self, tagcore):
        log.debug("Instantiating Tag() for %s", tagcore.tag)
        Tag(tagcore, self.callbacks)
        self.callbacks["set_var"]("needs_refresh", True)

    def on_del_tagcore(self, tagcore):
        log.debug("taglist on_del_tag")
        for tagobj in alltags:
            if tagobj.tag == tagcore.tag:
                tagobj.die()

        self.callbacks["set_var"]("needs_refresh", True)

    # We really shouldn't care about item being added (it's a TagCore event)
    # but we do need to release the gui thread so that it can handle sync
    # caused by an empty Tag's TagCore getting items.

    def on_items_added(self, tagcore, items):
        self.callbacks["release_gui"]()

    def on_items_removed(self, tagcore, items):
        self.callbacks["release_gui"]()

    def on_tag_updated(self, tagcore):
        self.callbacks["release_gui"]()

    def on_eval_tags_changed(self):
        self.callbacks["force_sync"]()
        self.callbacks["release_gui"]()

    # Called with sync_lock, so we are unrestricted.

    def on_stories_added(self, tag, items):
        # Items being added implies we need to remap them
        self.callbacks["set_var"]("needs_refresh", True)

    # Called with sync_lock, so we are unrestricted.

    def on_stories_removed(self, tag, items):
        # Items being removed implies we need to remap them.
        self.callbacks["set_var"]("needs_refresh", True)

    def on_opt_change(self, conf):
        if "taglist" not in conf:
            return

        if "search_attributes" in conf["taglist"]:
            log.info("Fetching any needed search attributes")

            need_attrs = {}
            sa = self.callbacks["get_opt"]("taglist.search_attributes")

            # Make sure that we have all attributes needed for a search.
            for tag in alltagcores:
                for item in tag:
                    tag_updater.need_attributes(item, sa)

        if "spacing" in conf["taglist"]:
            self.spacing = conf["taglist"]["spacing"]
            self.callbacks["set_var"]("needs_refresh", True)

    def cmd_goto(self, items):
        log.debug("GOTO: %s", items)
        self._goto([item.content["link"] for item in items])

    def cmd_tag_state(self, state, tags):
        attributes = {}
        for tag in tags:
            for item in tag:
                if item.handle_state(state):
                    attributes[item.id] = { "canto-state" : item.content["canto-state"] }

        if attributes:
            tag_updater.set_attributes(attributes)

    # item-state: Add/remove state for multiple items.

    def cmd_item_state(self, state, items):
        attributes = {}
        for item in items:
            if item.handle_state(state):
                attributes[item.id] = { "canto-state" : item.content["canto-state"] }

        if attributes:
            tag_updater.set_attributes(attributes)

    # tag-item : Same as above, with tags.

    def cmd_tag_item(self, tag, items):
        # Proper prefix
        if tag[0] in '-%':
            tag = tag[0] + "user:" + tag[1:]
        else:
            tag = "user:" + tag

        attributes = {}
        for item in items:
            if item.handle_tag(tag):
                attributes[item.id] = { "canto-tags" : item.content["canto-tags"] }

        if attributes:
            tag_updater.set_attributes(attributes)

    def cmd_tags(self, items):
        for item in items:
            if "title" in item.content:
                log.info("'%s' in tags:\n" % item.content["title"])

            log.info(item.parent_tag.tag)

            if "canto-tags" in item.content:
                for tag in item.content["canto-tags"]:
                    if tag.startswith("user:"):
                        log.info(tag[5:])
                    else:
                        log.info(tag)

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
            lines += o.lines(self.width)
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
            lines += o.lines(self.width)

        return (ps, lines)

    def cmd_rel_set_cursor(self, relidx):
        sel = self.callbacks["get_var"]("selected")
        if sel:
            target_idx = sel.sel_offset + relidx
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

            if curstyle["type"] == "bottom":
                window_location = 0
            elif curstyle["type"] == "middle":
                window_location = int((self.height - 1) / 2)
            elif curstyle["type"] == "top":
                window_location = self.height - 1

            # If the tag header is larger than the edge, the scroll will never
            # be triggered (redraw resets screen position to keep items visible
            # despite the tag header).

            tag = self.tag_by_obj(item)

            wl_top = max(curstyle["edge"], tag.lines(self.width))

            # Similarly, if the current item is larger than the (edge + 1), the
            # scroll won't be triggered, so we take the max edge there too.

            wl_bottom = (self.height - 1) - max(curstyle["edge"], item.lines(self.width))

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

    def cmd_foritems(self, items):
        self.got_items = items

    def cmd_foritem(self, items):
        if len(items) > 0:
            self.got_items = [ items[0] ]
        else:
            self.got_items = []

    # clearitems clears all the items set by foritems.

    def cmd_clearitems(self):
        log.debug("Clearing ITEMS!")
        self.got_items = []

    def cmd_page_up(self):
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
                    scroll -= sel.lines(self.width)
                    sel = sel.prev_obj

            self._set_cursor(sel, target_offset)
        else:
            while scroll > 0 and target_obj.prev_obj:
                target_obj = target_obj.prev_obj
                scroll -= target_obj.lines(self.width)

            self.callbacks["set_var"]("target_obj", target_obj)
            self.callbacks["set_var"]("target_offset", target_offset)
            self.callbacks["set_var"]("needs_redraw", True)

    def cmd_page_down(self):
        target_offset = self.callbacks["get_var"]("target_offset")
        target_obj = self.callbacks["get_var"]("target_obj")
        sel = self.callbacks["get_var"]("selected")

        # No items, forget about it.
        if not target_obj:
            return

        scroll = self.height - 1

        if sel:
            while scroll > 0 and sel.next_sel:
                if scroll < sel.lines(self.width):
                    break

                nstory = sel.next_sel
                while sel != nstory:
                    scroll -= sel.lines(self.width)
                    sel = sel.next_obj

            self._set_cursor(sel, target_offset)
        else:
            while scroll > 0 and target_obj.next_obj:
                scroll -= target_obj.lines(self.width)
                if scroll < 0:
                    break
                target_obj = target_obj.next_obj

            self.callbacks["set_var"]("target_obj", target_obj)
            self.callbacks["set_var"]("target_offset", 0)
            self.callbacks["set_var"]("needs_redraw", True)

    def cmd_next_tag(self):
        sel = self.callbacks["get_var"]("selected")

        if not sel:
            return self._set_cursor(self.first_sel, 0)

        target_offset = self.callbacks["get_var"]("target_offset")

        tag = self.tag_by_obj(sel)

        while sel and self.tag_by_obj(sel) == tag:
            if sel.next_sel == None:
                break
            sel = sel.next_sel

        self._set_cursor(sel, target_offset)

    def cmd_prev_tag(self):
        sel = self.callbacks["get_var"]("selected")

        if not sel:
            return self._set_cursor(self.first_sel, 0)

        target_offset = self.callbacks["get_var"]("target_offset")

        tag = self.tag_by_obj(sel)

        while sel and self.tag_by_obj(sel) == tag:
            if sel.prev_sel == None:
                break
            sel = sel.prev_sel

        if sel:
            newtag = self.tag_by_obj(sel)
            if newtag.collapsed:
                sel = newtag
            else:
                sel = newtag[0]

        self._set_cursor(sel, target_offset)

    def cmd_reader(self, items):
        self.callbacks["set_var"]("reader_item", items[0])
        self.callbacks["set_var"]("reader_offset", 0)
        self.callbacks["add_window"](Reader)

    def cmd_promote(self, tags):
        for tag in tags:

            log.debug("Promoting %s\n", tag.tag)

            # Refetch because a promote call will cause our eval_tag hook to
            # recreate visible_tags.

            visible_tags = self.callbacks["get_var"]("taglist_visible_tags")

            curidx = visible_tags.index(tag)

            # Obviously makes no sense on top tag.
            if curidx == 0:
                return

            # Re-order tags and update internal list order.
            self.callbacks["switch_tags"](tag.tag, visible_tags[curidx - 1].tag)

        self.callbacks["set_var"]("needs_refresh", True)

    def cmd_demote(self, tags):
        for tag in tags:

            log.debug("Demoting %s\n", tag.tag)

            visible_tags = self.callbacks["get_var"]("taglist_visible_tags")

            # Obviously makes no sense on bottom or only tag.
            if tag == visible_tags[-1] or len(visible_tags) == 1:
                return

            curidx = visible_tags.index(tag)
            self.callbacks["switch_tags"](tag.tag, visible_tags[curidx + 1].tag)

        self.callbacks["set_var"]("needs_refresh", True)

    def _collapse_tag(self, tag):
        log.debug("Collapsing %s\n", tag.tag)

        # If we're collapsing the selection, select
        # the tag instead.
        s = self.callbacks["get_var"]("selected")
        if s and s in tag:
            toffset = self.callbacks["get_var"]("target_offset")
            self._set_cursor(tag, toffset) 

        self.callbacks["set_tag_opt"](tag.tag, "collapsed", True)

    def cmd_collapse(self, tags):
        for tag in tags:
            self._collapse_tag(tag)

    def _uncollapse_tag(self, tag):
        log.debug("Uncollapsing %s\n", tag.tag)

        # If we're uncollapsing the selected tag,
        # go ahead and select the first item.

        s = self.callbacks["get_var"]("selected")
        if s and tag == s and len(tag) != 0:
            toffset = self.callbacks["get_var"]("target_offset") + tag.lines(self.width)
            self._set_cursor(tag[0], toffset)

        self.callbacks["set_tag_opt"](tag.tag, "collapsed", False)

    def cmd_uncollapse(self, tags):
        for tag in tags:
            self._uncollapse_tag(tag)

    def cmd_toggle_collapse(self, tags):
        for tag in tags:
            if self.callbacks["get_tag_opt"](tag.tag, "collapsed"):
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

    def cmd_search(self, term):
        if not term:
            term = self.callbacks["input"]("search:", False)
        if not term:
            return

        rgx = ".*" + re.escape(term) + ".*"
        return self.search(rgx)

    def cmd_search_regex(self, term):
        if not term:
            term = self.callbacks["input"]("search-regex:", False)
        if not term:
            return
        return self.search(term)

    def cmd_next_marked(self):
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

    def cmd_prev_marked(self):
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

    def type_user_tag(self):
        utags = []
        for tag in alltagcores:
            if tag.tag.startswith("user:"):
                utags.append(tag.tag[5:])

        return (utags, lambda x : (True, x))

    def type_category(self):
        def category_validator(x):
            if x.lower() == "none":
                return (True, None)
            else:
                return (True, x)

        categories = []
        for tag in alltagcores:
            if tag.tag.startswith("category:"):
                categories.append(tag.tag[9:])

        return (categories, category_validator)

    def cmd_categorize(self, category, tags):
        if not category:
            return
        for tag in tags:
            tc = self.callbacks["get_tag_conf"](tag.tag)

            fullcat = "category:" + category
            if fullcat not in tc["extra_tags"]:
                tc["extra_tags"].append(fullcat)
                self.callbacks["set_tag_conf"](tag.tag, tc)
                log.info("%s is now in category %s" % (tag, category))

    def cmd_remove_category(self, category, tags):
        if not category:
            return
        for tag in tags:
            tc = self.callbacks["get_tag_conf"](tag.tag)

            fullcat = "category:" + category
            if fullcat in tc["extra_tags"]:
                tc["extra_tags"].remove(fullcat)
                self.callbacks["set_tag_conf"](tag.tag, tc)
                log.info("%s is no longer in category %s" % (tag, category))

    def cmd_categories(self, tags):
        for tag in tags:
            tc = self.callbacks["get_tag_conf"](tag.tag)
            categories = [ x[9:] for x in tc["extra_tags"] if x.startswith("category:")]
            if categories == []:
                log.info("%s - No categories" % tag)
            else:
                log.info("%s - %s" % (tag, " ".join(categories)))

        popped_cats = []
        for tag in alltagcores:
            if tag.tag.startswith("category:"):
                popped_cats.append(tag.tag[9:])

        if popped_cats:
            log.info("\nAvailable categories:")
            for cat in popped_cats:
                log.info(cat)
        else:
            log.info("\nNo categories available.")

    def cmd_show_category(self, category):
        if category:
            tag_updater.transform("categories", "InTags(\'" + shlex.quote("category:" + category) + "\')")
        else:
            tag_updater.transform("categories", "None")
        tag_updater.update()

    def cmd_delfeed(self, tags):
        for tag in tags:
            if tag.tag.startswith("maintag:"):
                self._remote_argv(["canto-remote", "delfeed", tag.tag[8:]])
            else:
                log.info("tag %s is not a feed tag")

    def update_tag_lists(self):
        curtags = self.callbacks["get_var"]("curtags")
        self.tags = []

        # Make sure to honor the order of tags in curtags.

        for tag in curtags:
            for tagobj in alltags:
                if tagobj.tag == tag:
                    self.tags.append(tagobj)

        # If selected is stale (i.e. its tag was deleted, the item should stick
        # around in all other cases) then unset it.

        sel = self.callbacks["get_var"]("selected")
        tobj = self.callbacks["get_var"]("target_obj")

        if sel and ((sel.is_tag and sel not in self.tags) or (not sel.is_tag and sel.is_dead)):
            log.debug("Stale selection")
            self.callbacks["set_var"]("selected", None)

        if tobj and ((tobj.is_tag and tobj not in self.tags) or (not tobj.is_tag and tobj.is_dead)):
            log.debug("Stale target obj")
            self.callbacks["set_var"]("target_obj", None)
            self.callbacks["set_var"]("target_offset", 0)

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

            t.append(tag)

        self.callbacks["set_var"]("taglist_visible_tags", t)

    def update_target_obj(self):
        # Set initial target_obj if none already set, or if it's stale.

        target_obj = self.callbacks["get_var"]("target_obj")

        if target_obj:
            return

        vistags = self.callbacks["get_var"]("taglist_visible_tags")

        if vistags:
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
            tag.curpos = self.height

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
                story.curpos = self.height

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
        lines = obj.pads(self.width)
        pad = obj.pad

        if footer:
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
        log.debug("Taglist REDRAW (%s)!\n", self.width)
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

        if not target_obj.is_tag:
            tag = target_obj.parent_tag
            tl = tag.lines(self.width)
            if target_offset < tl:
                target_offset = tl
        elif target_offset < 0:
            target_offset = 0

        # If we're trying to render too close to the bottom, we also
        # need an adjustment.

        tol = target_obj.lines(self.width)
        if target_offset > ((self.height - 1) - tol):
            target_offset = (self.height - 1) - tol

        # Step 1. Find first object based on target_obj and target_offset,
        # This will cause any changes to be resolved for objects on screen
        # before and including the target object.

        obj = target_obj
        curpos = target_offset
        top_adjusted = False

        while curpos > 0:
            if obj.prev_obj:
                curpos -= obj.prev_obj.lines(self.width)
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
                last_off += last_obj.lines(self.width)
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
        while self.first_sel.is_tag:

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
            obj.lines(self.width)
            obj.curpos = curpos

            # Copy item into window
            w_offset, curpos = self._partial_render(obj, w_offset, curpos)

            # Render floating header, if we've covered enough ground.

            if not rendered_header and curpos > 0:
                tag = self.tag_by_obj(obj)

                if curpos >= tag.lines(self.width):
                    self._partial_render(tag, 0, 0)
                    rendered_header = True

            # If we're at the end of a list, or the next item is a tag we need
            # to render the tag footer for the current tag.

            obj.extra_lines = 0

            if (not obj.next_obj) or obj.next_obj.is_tag:
                if obj.is_tag:
                    tag = obj
                else:
                    tag = self.tag_by_item(obj)
                    tag.lines(self.width)
                    obj.extra_lines = tag.footlines

                w_offset, curpos = self._partial_render(tag, w_offset, curpos, True)

                # Set this because if we don't have room above the footer for
                # the header (implied by this block executing with
                # rendered_header == False), then actually rendering one looks
                # broken.

                rendered_header = True
            elif (not obj.is_tag) and self.spacing:
                curpos += self.spacing
                w_offset += self.spacing
                obj.extra_lines += self.spacing

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
