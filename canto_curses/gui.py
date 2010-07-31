# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from theme import theme_print, theme_len, theme_process, WrapPad, FakePad
from command import CommandHandler, command_format, generic_parse_error
from html import htmlparser, char_ref_convert, html_entity_convert
from canto.encoding import encoder
from utility import silentfork
from input import InputBox
from consts import *

import logging

log = logging.getLogger("GUI")

from threading import Thread, Event
from Queue import Queue
import curses
import signal
import time

class Reader(CommandHandler):
    def init(self, pad, callbacks):
        self.pad = pad
        self.callbacks = callbacks
        self.keys = {}

    def refresh(self):
        self.redraw()

    def redraw(self):
        log.debug("Reader redraw!")
        self.pad.erase()

        mwidth = self.pad.getmaxyx()[1]
        pad = WrapPad(self.pad)

        sel = self.callbacks["get_var"]("selected")
        if not sel:
            self.pad.addstr("No selected story.")
        else:
            if "description" not in sel.content:
                self.callbacks["write"]("ATTRIBUTES", { sel.id : [
                    "description" ] } )
                self.callbacks["set_var"]("needs_deferred_redraw", True)
                s = "%BWaiting for content...%b"
            else:
                s = "%B" + sel.content["title"] + "%b\n"
                c, l = htmlparser.convert(sel.content["description"])
                s += c

            while s:
                s = s.lstrip(" \t\v").rstrip(" \t\v")
                s = theme_print(pad, s, mwidth, " ", " ")

        self.callbacks["refresh"]()

    def command(self, cmd):
        pass

    def get_height(self, mheight):
        return mheight

    def get_width(self, mwidth):
        return mwidth

# The Story class is the basic wrapper for an item to be displayed. It manages
# its own state only because it affects its representation, it's up to a higher
# class to actually communicate state changes to the backend.

class Story():
    def __init__(self, id, callbacks):
        self.callbacks = callbacks
        self.content = {}
        self.id = id
        self.selected = False
        self.cached_state = {}

    # Add / remove state. Return True if an actual change, False otherwise.

    def handle_state(self, attr):
        if self.content["canto-state"] == "":
            self.content["canto-state"] = []

        # Negative attribute
        if attr[0] == "-":
            attr = attr[1:]
            if attr in self.content["canto-state"]:
                self.content["canto-state"].remove(attr)
                return True

        # Positive attribute
        elif attr not in self.content["canto-state"]:
            self.content["canto-state"].append(attr)
            return True

        return False

    def select(self):
        self.selected = True

    def unselect(self):
        self.selected = False

    def refresh(self, mwidth, idx):
        # Do we need the enumerated form?
        enumerated = self.callbacks["get_var"]("enumerated")

        # These are the only things that affect the drawing
        # of this item.

        state = { "mwidth" : mwidth,
                  "idx" : idx,
                  "enumerated" : enumerated,
                  "state" : self.content["canto-state"][:],
                  "selected" : self.selected }

        # If the last refresh call had the same parameters and
        # settings, then we don't need to touch the actual pad.

        if self.cached_state == state:
            return self.pad.getmaxyx()[0]

        self.cached_state = state

        # Render once to a FakePad (no IO) to determine the correct
        # amount of lines. Force this to enumerated = 0 because
        # we don't want the enumerated content to take any more lines
        # than the unenumerated. Render will truncate smartly if we
        # attempt to go over. This avoids insane amounts of line shifting
        # when enumerating items and allows us to get the perfect size
        # for this story's pad.

        lines = self.render(FakePad(mwidth), mwidth, idx, 0)

        # Create the new pad and actually do the render.

        self.pad = curses.newpad(lines, mwidth)
        return self.render(WrapPad(self.pad), mwidth, idx, enumerated)

    def render(self, pad, mwidth, idx, enumerated):

        # The first render step is to get a big long line
        # describing what we want to render with the
        # given state.

        pre = ""
        post = ""

        if self.selected:
            pre = "%R" + pre
            post = post + "%r"

        if self.content["canto-state"] and\
                "read" in self.content["canto-state"]:
            pre = pre + "%3"
            post = "%0" + post
        else:
            pre = pre + "%2%B"
            post = "%b%0" + post

        if enumerated:
            pre = ("[%d] " % idx) + pre

        s = pre + self.content["title"] + post

        # s is now a themed line based on this story.
        # This doesn't include a border.

        lines = 0

        left = u"%C%1│%0 %c"
        left_more = u"%C%1│%0     %c"
        right = u"%C %1│%0%c"

        try:
            while s:
                # Left border, for first line
                if lines == 0:
                    l = left

                # Left border, for subsequent lines (indent)
                else:
                    l = left_more

                s = theme_print(pad, s, mwidth, l, right)

                # Avoid line shifting when temporarily enumerating.
                if s and enumerated and\
                        lines == (self.unenumerated_lines - 1):
                    pad.move(pad.getyx()[0],\
                            pad.getyx()[1] - (theme_len(right) + 3))

                    # Write out the ellipsis.
                    for i in xrange(3):
                        pad.waddch('.')

                    # Handling any dangling codes
                    theme_process(pad, s)
                    s = None

                # Keep track of lines for this item
                lines += 1

            # Keep track of unenumerated lines so that we can
            # do the above shift-avoiding.

            if not enumerated:
                self.unenumerated_lines = lines

        # Render exceptions should be non-fatal. The worst
        # case scenario is that one story's worth of space
        # is going to be fucked up.

        except Exception, e:
            log.debug("Story exception: %s" % (e,))

        # Return number of lines this story took to render entirely.
        return lines

    # Return what attributes of this story are needed
    # to render it. Eventually this will be determined
    # on the client render string.

    def needed_attributes(self):
        return [ "title", "link", "canto-state" ]

# The Tag class manages stories. Externally, it looks
# like a Tag takes IDs from the backend and renders an ncurses pad. No class
# other than Tag actually touches Story objects directly.

class Tag(list):
    def __init__(self, tag, callbacks):
        list.__init__(self)

        # Note that Tag() is only given the top-level CantoCursesGui
        # callbacks as it shouldn't be doing input / refreshing
        # itself.

        self.callbacks = callbacks
        self.tag = tag

        # Upon creation, this Tag adds itself to the
        # list of all tags.

        callbacks["get_var"]("alltags").append(self)

    # We override eq so that empty tags don't evaluate
    # as equal and screw up things like enumeration.

    def __eq__(self, other):
        if self.tag != other.tag:
            return False
        return list.__eq__(self, other)

    # Create Story from ID before appending to list.
    def append(self, id):
        s = Story(id, self.callbacks)
        list.append(self, s)

    def get_id(self, id):
        for item in self:
            if item.id == id:
                return item
        return None

    def refresh(self, mwidth, idx_offset):

        lines = self.render_header(mwidth, FakePad(mwidth))

        self.header_pad = curses.newpad(lines, mwidth)

        for i, item in enumerate(self):
            lines += item.refresh(mwidth, idx_offset + i)

        # Create a new pad with enough lines to
        # include all story objects.
        self.pad = curses.newpad(lines, mwidth)

        return self.render(mwidth, WrapPad(self.pad))

    def render_header(self, mwidth, pad):
        enumerated = self.callbacks["get_var"]("tags_enumerated")
        header = self.tag + u"\n"
        if enumerated:
            curtags = self.callbacks["get_var"]("curtags")
            header = ("[%d] " % curtags.index(self)) + header

        lines = 0

        while header:
            header = theme_print(pad, header, mwidth, u"│", u"│")
            lines += 1

        return lines

    def render(self, mwidth, pad):
        # Update header_pad (used to float tag header)
        self.render_header(mwidth, WrapPad(self.header_pad))

        # Render to the taglist pad as well.
        spent_lines = self.render_header(mwidth, pad)
        mp = [spent_lines]

        for item in self:
            cur_lines = item.pad.getmaxyx()[0]
            mp.append(cur_lines)

            # Copy the item pad into the Tag's pad.
            item.pad.overwrite(self.pad, 0, 0, spent_lines, 0,\
                spent_lines + cur_lines - 1 , mwidth - 1)

            spent_lines += cur_lines

        # Return a list of integers, the heights of the header,
        # and all of the stories. The sum must == the height
        # of the tag's pad.
        return mp

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

    def get_height(self, mheight):
        return mheight

    def get_width(self, mwidth):
        return mwidth

# The Screen class handles the layout of multiple sub-windows on the 
# main curses window. It's also the top-level gui object, so call to refresh the
# screen and get input should come through it.

class Screen(CommandHandler):
    def init(self, user_queue, callbacks, layout = [[TagList],InputBox]):
        self.user_queue = user_queue
        self.callbacks = callbacks
        self.layout = layout

        self.keys = {}

        self.stdscr = curses.initscr()
        if self.curses_setup() < 0:
            return -1

        self.pseudo_input_box = curses.newpad(1,1)
        self.pseudo_input_box.keypad(1)

        self.input_box = None
        self.sub_edit = False

        self.subwindows()

        # Start grabbing user input
        self.start_input_thread()

    def curses_setup(self):
        # This can throw an exception, but we shouldn't care.
        try:
            curses.curs_set(0)
        except:
            pass

        try:
            curses.cbreak()
            curses.noecho()
            curses.start_color()
            curses.use_default_colors()
        except Exception, e:
            log.error("Curses setup failed: %s" % e.msg)
            return -1

        self.height, self.width = self.stdscr.getmaxyx()

        for i, c in enumerate([ 7, 4, 3, 4, 2 ]):
            curses.init_pair(i + 1, c, -1)

        return 0

    # Translate the layout into a set of curses pads given
    # a set of coordinates relating to how they're mapped to the screen.

    def _subw_init(self, ci, ct, top, left, width, height):
        # This will grab the last inputbox instantiated,
        # though others seem pointless anyway.

        if ct == InputBox:
            self.input_box = ci

        # Height - 1 because start + height = line after bottom.

        bottom = top + (height - 1)
        right = left + (width - 1)

        refcb = lambda : self.refresh_callback(ci, top, left, bottom, right)

        # Height + 1 to account for the last curses pad line
        # not being fully writable.

        pad = curses.newpad(height + 1, width)

        # Pass on callbacks we were given from CantoCursesGui
        # plus our own.

        callbacks = self.callbacks.copy()
        callbacks["refresh"] = refcb
        callbacks["input"] = self.input_callback

        ci.init(pad, callbacks)

        self.windows.append(ci)

    # Layout some windows into the given space, stacking with
    # orientation horizontally or vertically.

    def _subw(self, layout, top, left, height, width, orientation):
        immediates = []
        cmplx = []
        ret = [0] * len(layout)
        sizes = [0] * len(layout)

        # Separate windows in to two categories:
        # immediates that are defined as base classes and
        # cmplx which are lists for further processing (iterables)

        for i, unit in enumerate(layout):
            if hasattr(unit, "__iter__"):
                cmplx.append((i, unit))
            else:
                immediates.append((i,unit))

        # Units are the number of windows we'll have
        # to split the area with.

        units = len(layout)

        # Used, the amounts of space already used.
        used = 0

        # Instances, used later.
        imm_instances = []

        for i, unit in immediates:
            # Grab an instance
            ci = unit()
            imm_instances.append((i, ci))

            # Get the size of the window from the class.
            # Each class is given, as a maximum, the largest
            # possible slice we can *guarantee*.

            if orientation == "horizontal":
                size = ci.get_width((width - used) / units)
            else:
                size = ci.get_height((height - used) / units)

            used += size

            sizes[i] = size
            ret[i] = ci

            # Subtract so that the next run only divides
            # the remaining space by the number of units
            # that don't have space allocated.

            units -= 1

        # All of the immediates have been allocated for.
        # So now only the cmplxs are vying for space.

        units = len(cmplx)


        for i, unit in cmplx:
            offset = sum(sizes[0:i])

            # Recursives call this function, alternating
            # the orientation, for the space we can guarantee
            # this set of windows.

            if orientation == "horizontal":
                available = (width - used) / units
                r = self._subw(unit, top, left + offset,\
                        height, available, "vertical")
                sizes[i] = max([x.pad.getmaxyx()[1] - 1 for x in r])
            else:
                available = (height - used) / units
                r = self._subw(unit, top + offset, left,\
                        available, width, "horizontal")
                sizes[i] = max([x.pad.getmaxyx()[0] - 1 for x in r])

            ret[i] = r
            used += sizes[i]
            units -= 1

        # Now that we know the actual sizes (and thus locations) of
        # the windows, we actually setup the immediates.

        for i, ci in imm_instances:
            offset = sum(sizes[0:i])
            if orientation == "horizontal":
                self._subw_init(ci, layout[i], top, left + offset,
                        sizes[i], height)
            else:
                self._subw_init(ci, layout[i], top + offset, left,
                        width, sizes[i])

        return ret

    def subwindows(self):
        self.stdscr.erase()
        self.stdscr.refresh()

        self.focused = None
        self.windows = []

        self._subw(self.layout, 0, 0, self.height, self.width, "vertical")

        # Default to giving first window focus.
        self._focus(0)

    def refresh_callback(self, c, t, l, b, r):
        log.debug("args: %s" % ((c, t, l, b, r),))
        c.pad.noutrefresh(0, 0, t, l, b, r)

    def input_callback(self, prompt):
        # Setup subedit
        self.input_done.clear()
        self.input_box.edit(prompt)
        self.sub_edit = True

        # Wait for finished input
        self.input_done.wait()

        # Grab the return and reset
        r = self.input_box.result
        self.input_box.reset()
        return r

    def classtype(self, args):
        t, r = self._first_term(args, lambda : self.input_callback("class: "))

        if t == "taglist":
            return (True, TagList, r)
        elif t == "reader":
            return (True, Reader, r)

        log.error("Unknown class: %s" % t)
        return (False, None, None)

    def optint(self, args):
        if not args:
            return (True, 0, "")
        t, r = self._first_term(args, None)
        try:
            t = int(t)
        except:
            log.error("Can't parse %s as integer" % t)
            return (False, None, None)
        return (True, t, r)

    def refresh(self):
        for c in self.windows:
            c.refresh()
        curses.doupdate()

    def redraw(self):
        for c in self.windows:
            c.redraw()
        curses.doupdate()

    @command_format("resize", [])
    @generic_parse_error
    def resize(self, **kwargs):
        try:
            curses.endwin()
        except:
            pass

        # Re-enable keypad on the input box because
        # apparently endwin unsets it. Must be done
        # before the stdscr.refresh() or the first
        # keypress after KEY_RESIZE doesn't get translated
        # (you get raw bytes).

        self.pseudo_input_box.keypad(1)
        self.stdscr.refresh()

        self.curses_setup()
        self.subwindows()
        self.refresh()

    # Focus idx-th instance of cls.
    @command_format("focus", [("idx", "optint")])
    @generic_parse_error
    def focus(self, **kwargs):
        self._focus(kwargs["idx"])

    def _focus(self, idx):
        l = len(self.windows)
        if -1 * l < idx < l:
            self.focused = self.windows[idx]
            log.debug("Focusing window %d (%s)" % (idx, self.focused))
        else:
            log.debug("Couldn't find window %d" % idx)

    def _window_levels(self, toplevel):
        for i in reversed(toplevel):
            if hasattr(i, "__iter__"):
                return [self] + [ self._window_levels(i) ]
        return toplevel

    @command_format("add-window", [("cls","classtype")])
    @generic_parse_error
    def add_window(self, **kwargs):
        self._add_window(kwargs["cls"])

    def _add_window(self, cls):
        self._window_levels(self.layout)[-1].append(cls)
        self.subwindows()
        self._focus(0)
        self.refresh()

    # Pass a command to focused window:

    def command(self, cmd):
        if cmd.startswith("focus"):
            self.focus(args=cmd)
        elif cmd.startswith("resize"):
            self.resize(args=cmd)
        elif cmd.startswith("add-window"):
            self.add_window(args=cmd)

        # Propagate command to focused window
        else:
            self.focused.command(cmd)

    def key(self, k):
        r = CommandHandler.key(self, k)
        if r:
            return r
        if self.focused:
            return self.focused.key(k)
        return None

    def input_thread(self):
        while True:
            r = self.pseudo_input_box.getch()

            log.debug("R = %s" % r)

            # We're in an edit box
            if self.sub_edit:
                # Feed the key to the input_box
                rc = self.input_box.addkey(r)

                # If rc == 1, need more keys
                # If rc == 0, all done (result could still be "" though)
                if not rc:
                    self.sub_edit = False
                    self.input_done.set()
                    self.callbacks["set_var"]("needs_redraw", True)
                continue

            # We're not in an edit box.

            # Convert to a writable character, if in the ASCII range
            if r < 256:
                r = chr(r)

            self.user_queue.put(("KEY", r))

    def start_input_thread(self):
        self.input_done = Event()
        self.inthread =\
                Thread(target = self.input_thread)

        self.inthread.daemon = True
        self.inthread.start()

    def exit(self):
        curses.endwin()

class CantoCursesGui(CommandHandler):
    def init(self, backend, do_curses=True):
        self.backend = backend

        # Variables that affect the overall operation.
        # We use the same list for alltags and curtags
        # so that, if curtags isn't set explicity, it
        # automatically equals alltags

        td = []
        self.vars = {
            "tags_enumerated" : False,
            "enumerated" : False,
            "selected" : None,
            "curtags" : td,
            "alltags" : td,
            "needs_refresh" : False,
            "needs_redraw" : False,
            "needs_deferred_redraw" : False
        }

        callbacks = {
                "set_var" : self.set_var,
                "get_var" : self.get_var,
                "write" : self.backend.write
        }

        self.keys = {
                ":" : "command",
                "q" : "quit"
        }

        self.backend.write("LISTFEEDS", u"")
        r = self.wait_response("LISTFEEDS")
        self.tracked_feeds = r[1]

        # Initial tag populate.

        item_tags = []
        for tag, URL in self.tracked_feeds:
            log.info("Tracking [%s] (%s)" % (tag, URL))
            t = Tag(tag, callbacks)
            item_tags.append(tag)

        self.backend.write("ITEMS", item_tags)
        r = self.wait_response("ITEMS")

        for tag in self.vars["alltags"]:
            for item in r[1][tag.tag]:
                tag.append(item)

        # Initial story attribute populate.

        attribute_stories = {}

        for tag in self.vars["alltags"]:
            for story in tag:
                attribute_stories[story.id] = story.needed_attributes()

        self.backend.write("ATTRIBUTES", attribute_stories)
        r = self.wait_response("ATTRIBUTES")
        self.attributes(r[1])

        # Short circuit for testing the above setup.
        if do_curses:
            log.debug("Starting curses.")
            self.screen = Screen()
            self.screen.init(self.backend.responses, callbacks)
            self.screen.refresh()

    def next_response(self, timeout=0):
        return self.backend.responses.get()

    def wait_response(self, cmd):
        log.debug("waiting on %s" % cmd)
        while True:
            r = self.next_response()
            if r[0] == cmd:
                return r
            else:
                log.debug("waiting: %s != %s" % (r[0], cmd))

    def attributes(self, d):
        for given_id in d:
            if not d[given_id]:
                log.debug("Caught item disappearing.")
                continue

            for tag in self.vars["alltags"]:
                item = tag.get_id(given_id)
                if not item:
                    continue

                for k in d[given_id]:
                    a = d[given_id][k]
                    if type(a) == unicode:
                        a = a.replace("\\", "\\\\")
                        a = a.replace("%", "\\%")
                        a = html_entity_convert(a)
                        a = char_ref_convert(a)
                        item.content[k] = a
                    else:
                        item.content[k] = a

    def var(self, args):
        t, r = self._first_term(args,\
                lambda : self.screen.input_callback("var: "))
        if t in self.vars:
            return (True, t, r)
        log.error("Unknown variable: %s" % t)
        return (False, None, None)

    @command_format("set", [("var","var")])
    @generic_parse_error
    def set(self, **kwargs):
        self.set_var(kwargs["var"], True)

    @command_format("unset", [("var","var")])
    @generic_parse_error
    def unset(self, **kwargs):
        self.set_var(kwargs["var"], False)

    @command_format("toggle", [("var","var")])
    @generic_parse_error
    def toggle(self, **kwargs):
        var = kwargs["var"]
        self.set_var(var, not self.get_var(var))

    def set_var(self, tweak, value):
        changed = False
        if self.vars[tweak] != value:
            self.vars[tweak] = value
            changed = True

        # Special actions on certain vars changed.
        if changed:
            if tweak in ["tags_enumerated", "enumerated"]:
                self.screen.refresh()

    def get_var(self, tweak):
        if tweak in self.vars:
            return self.vars[tweak]
        return None

    def winch(self):
        self.backend.responses.put(("CMD", "resize"))

    def key(self, k):
        r = CommandHandler.key(self, k)
        if r:
            return r
        return self.screen.key(k)

    # Search for unescaped & to split up multiple commands.
    def cmd_split(self, cmd):
        r = []
        escaped = False
        acc = ""
        for c in cmd:
            if escaped:
                acc += c
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == "&":
                r.append(acc)
                acc = ""
            else:
                acc += c
        r.append(acc)

        # lstrip all commands because we
        # want to use .startswith instead of a regex.
        return [ s.lstrip() for s in r ]

    def run(self):
        # Priority commands allow a single
        # user inputed string to actually
        # break down into multiple actions.
        priority_commands = []

        while True:
            if priority_commands:
                cmd = ("CMD", priority_commands[0])
                priority_commands = priority_commands[1:]
            else:
                cmd = self.backend.responses.get()

            if cmd[0] == "KEY":
                resolved = self.key(cmd[1])
                if not resolved:
                    continue
                cmd = ("CMD", resolved)

            # User command
            if cmd[0] == "CMD":
                log.debug("CMD: %s" % cmd[1])

                # Sub in a user command on the fly.
                if cmd[1] == "command":
                    cmd = ("CMD", self.screen.input_callback(":"))
                    log.debug("command resolved to: %s" % cmd[1])

                cmds = self.cmd_split(cmd[1])

                # If this is actually multiple commands,
                # then append them to the priority queue
                # and continue to execute them one at a time.

                if len(cmds) > 1:
                    log.debug("single command split into: %s" % cmds)
                    priority_commands.extend(cmds)
                    continue

                if cmd[1] in ["quit", "exit"]:
                    self.screen.exit()
                    self.backend.exit()
                    return

                # Variable Operations
                elif cmd[1].startswith("set"):
                    self.set(args=cmd[1])
                elif cmd[1].startswith("unset"):
                    self.unset(args=cmd[1])
                elif cmd[1].startswith("toggle"):
                    self.toggle(args=cmd[1])

                # Propagate command to screen / subwindows
                elif cmd[1] != "noop":
                    self.screen.command(cmd[1])

            elif cmd[0] == "ATTRIBUTES":
                self.attributes(cmd[1])

            # XXX Server notification/reply

            if self.vars["needs_refresh"]:
                log.debug("Needed refresh")
                self.screen.refresh()
                self.vars["needs_refresh"] = False
                self.vars["needs_redraw"] = False
            elif self.vars["needs_redraw"]:
                log.debug("Needed redraw")
                self.screen.redraw()
                self.vars["needs_redraw"] = False

            if self.vars["needs_deferred_redraw"]:
                self.vars["needs_deferred_redraw"] = False
                self.vars["needs_redraw"] = True
