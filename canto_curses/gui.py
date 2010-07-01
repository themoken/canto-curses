# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from theme import theme_print, theme_len, theme_process, WrapPad, FakePad
from command import CommandHandler, command_format, generic_parse_error
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

# Globals
# Yes, I know, this is Python.

curtags = []
alltags = []

needs_refresh = False
needs_redraw = False

class Story():
    def __init__(self, id, callbacks):
        # Note that Story() is only given the top-level CantoCursesGui
        # callbacks as it shouldn't be doing input / refreshing
        # itself.

        self.callbacks = callbacks
        self.content = {}
        self.id = id
        self.selected = False
        self.touched = True

    # Add / remove state. Return True if an actual change, False otherwise.

    def handle_state(self, attr):
        if self.content["canto-state"] == "":
            self.content["canto-state"] = []

        # Negative attribute
        if attr[0] == "-":
            attr = attr[1:]
            if attr in self.content["canto-state"]:
                self.content["canto-state"].remove(attr)
                self.touched = True
                return True

        # Positive attribute
        elif attr not in self.content["canto-state"]:
            self.content["canto-state"].append(attr)
            self.touched = True
            return True

        return False

    def select(self):
        self.selected = True
        self.touched = True

    def unselect(self):
        self.selected = False
        self.touched = True

    def needs_update(self):
        return self.touched

    def updated(self):
        self.touched = False

    def enumeration_prefix(self, idx):
        return "%1%B[" + str(idx) + "]%b%0 "

    def render(self, idx = 0):
        if self.content["canto-state"] and\
                "read" in self.content["canto-state"]:
            pre = "%3"
            post = "%0"
        else:
            pre = "%2%B"
            post = "%b%0"

        if self.selected:
            pre = "%R" + pre
            post = post + "%r"

        return pre + self.content["title"] + post

    # Return what attributes of this story are needed
    # to render it. Eventually this will be determined
    # on the client render string.

    def needed_attributes(self):
        return [ "title", "link", "canto-state" ]

class Tag(list):
    def __init__(self, tag, callbacks):
        # Note that Tag() is only given the top-level CantoCursesGui
        # callbacks as it shouldn't be doing input / refreshing
        # itself.

        self.callbacks = callbacks
        self.tag = tag
        alltags.append(self)

        self.cached_render_return = None
        self.cached_state = {}

    # Create Story from ID before appending to list.

    def append(self, id):
        s = Story(id, self.callbacks)
        list.append(self, s)

    def refresh(self, mwidth, idx_offset):
        # First, determine if we need to update.

        enumerated = self.callbacks["get_tweakable"]("enumerated")

        state = { "enumerated" : enumerated,
                  "mwidth" : mwidth,
                  "idx_offset" : idx_offset}

        if self.cached_render_return and state == self.cached_state:
            for item in self:
                if item.needs_update():
                    break
            else:
                return self.cached_render_return

        # Now we know we needed an update.

        # Render once, doing no I/O to get proper dimensions

        # We force enumerated = 0 on this run so we know
        # the correct number of lines to truncate enumerated lines
        # on the next call, because the number of lines shouldn't
        # be different ... although a future tweakable should let
        # user initiated enumeration shift lines, but automatically
        # initiated enumeration not.

        height = sum(self.render(mwidth, FakePad(mwidth), idx_offset, 0))

        # Create a custom pad
        self.pad = curses.newpad(height, mwidth)

        # Render again, actually drawing to the screen,
        # return ( new idx_offset, display lines for tag)

        self.cached_render_return =\
                self.render(mwidth, WrapPad(self.pad), idx_offset, enumerated)
        self.cached_state = state

        # All items are rendered as are, no updates needed.
        for item in self:
            item.updated()

        return self.cached_render_return

    def render(self, mwidth, pad, idx_offset, enumerated):

        left = u"%1│%0 "
        left_more = u"%1│%0     "
        right = u" %1│%0"

        header = self.tag + u"\n"
        lheader = theme_len(header)
        theme_print(pad, header, lheader)

        # Header takes 1 line
        mp = [1]

        for i, item in enumerate(self):
            try:
                s = item.render(idx_offset + i)
                if enumerated:
                    s = item.enumeration_prefix(idx_offset + i) + s

                lines = 0
                while s:
                    width = mwidth

                    # Left border
                    if lines == 0:
                        l = left
                    else:
                        l = left_more
                    llen = theme_len(l)
                    theme_print(pad, l, llen)
                    width -= llen

                    # Account for right border
                    rlen = theme_len(right)
                    width -= rlen

                    if width < 1:
                        raise Exception, "Not wide enough!"

                    # Print body
                    t = theme_print(pad, s, width)
                    if s == t:
                        raise Exception, "theme_print didn't advance!"
                    s = t

                    # Avoid line shifting when temporarily enumerating.
                    if s and enumerated and\
                            lines == (item.unenumerated_lines - 1):
                        remaining = (mwidth - rlen) - pad.getyx()[1]

                        # If we don't have enough room left in the line
                        # for the ellipsis naturally (because of a word
                        # break, etc), then we roll the cursor back and
                        # overwrite those characters.

                        if remaining < 3:
                            pad.move(pad.getyx()[0], pad.getyx()[1] -\
                                    (3 - remaining))

                        # Write out the ellipsis.
                        for i in xrange(3):
                            pad.waddch('.')

                        # Handling any dangling codes
                        theme_process(pad, s)
                        s = None

                    # Spacer for right border
                    while pad.getyx()[1] < (mwidth - rlen):
                        pad.waddch(' ')

                    # Right border
                    theme_print(pad, right, rlen)

                    # Keep track of lines for this item
                    lines += 1

                if not enumerated:
                    item.unenumerated_lines = lines

                # Keep track of lines-per-item
                mp.append(lines)

            except Exception, e:
                log.error("addstr excepted: %s" % (e, ))

        # Returns lines in header + lines-per-item
        return mp

# TagList is the class renders a classical Canto list of tags into the given
# panel. It defers to the Tag class for the actual individual tag rendering.

class TagList(CommandHandler):
    def init(self, pad, callbacks):
        # Drawing information
        self.pad = pad
        self.height, self.width = self.pad.getmaxyx()
        self.offset = 0

        # Selection information
        self.sel = None

        # Callback information
        self.callbacks = callbacks

        # Tags to be displayed.
        if not curtags:
            self.tags = alltags
        else:
            self.tags = curtags

        self.refresh()

    def item_by_idx(self, idx):
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

    def enumerate_and_input(self, prompt):
        # Ensure the items are enumerated
        t = self.callbacks["get_tweakable"]("enumerated")
        self.callbacks["set_tweakable"]("enumerated", True)

        r = self.callbacks["input"](prompt)

        # Reset enumerated to previous value
        self.callbacks["set_tweakable"]("enumerated", t)
        return r

    # For Command processing
    def input(self, prompt):
        return self.callbacks["input"](prompt)

    # Prompt that ensures the items are enumerated first
    def eprompt(self, prompt, value):

        # If there's already a value, no need for
        # enumeration or refresh.

        if value:
            return self.prompt(prompt, value)

        # Ensure the items are enumerated
        t = self.callbacks["get_tweakable"]("enumerated")
        self.callbacks["set_tweakable"]("enumerated", True)

        r = self.prompt(prompt, value)

        # Reset enumerated to previous value
        self.callbacks["set_tweakable"]("enumerated", t)
        return r

    # Will enumerate tags in the future.
    def teprompt(self, prompt, value):
        return self.prompt(prompt, value)

    @command_format("goto\s+(?P<sel_idx>\d+)\s*$")
    @command_format("goto\s*(?P<eprompt_goto_listof_int>\d+(\s*,\s*\d+)*)?\s*$")
    @generic_parse_error
    def goto(self, **kwargs):

        # Single number variant
        if "sel_idx" in kwargs:
            items = [self.item_by_idx(int(kwargs["sel_idx"]))]

        # Multiple idx variant
        elif "eprompt_goto_listof_int" in kwargs:
            items = [self.item_by_idx(i) for i in\
                    kwargs["eprompt_goto_listof_int"]]

        for item in items:
            if not item:
                continue
            silentfork(None, item.content["link"])

    @command_format("tag-state\s*(?P<prompt_state_string>[0-9A-Za-z-]+)?(?P<teprompt_tags_listof_int>\s+\d+(\s*,\s*\d+)*)?\s*$")
    @generic_parse_error
    def tag_state(self, **kwargs):
        global needs_redraw
        log.debug("TAG_STATE: %s" % kwargs)

        attributes = {}
        for i in kwargs["teprompt_tags_listof_int"]:
            if i >= len(self.tags):
                continue
            tag = self.tags[i]
            for item in tag:
                if item.handle_state(kwargs["prompt_state_string"]):
                    attributes[item.id] =\
                            { "canto-state" : item.content["canto-state"]}

        if attributes != {}:
            self.refresh()
            needs_redraw = True
            self.callbacks["write"]("SETATTRIBUTES", attributes)

    @command_format("item-state\s*(?P<prompt_state_string>[0-9A-Za-z-]+)?(?P<eprompt_items_listof_int>\s+\d+(\s*,\s*\d+)*)?\s*$")
    @generic_parse_error
    def item_state(self, **kwargs):
        global needs_redraw
        attributes = {}
        for idx in kwargs["eprompt_items_listof_int"]:
            item = self.item_by_idx(idx)
            if not item:
                continue
            if item.handle_state(kwargs["prompt_state_string"]):
                attributes[item.id] =\
                        { "canto-state" : item.content["canto-state"] }

        if attributes:
            self.refresh()
            needs_redraw = True
            self.callbacks["write"]("SETATTRIBUTES", attributes)

    # set-cursor is *absolute* and will not argue about indices that
    # don't exist, it will just unselect negative or too high indices.

    @command_format("set-cursor\s*(?P<eprompt_idx_int>[0-9-]+)?\s*$")
    @generic_parse_error
    def set_cursor(self, **kwargs):
        idx = kwargs["eprompt_idx_int"]

        if idx < 0:
            self._set_cursor(None)
        else:
            self._set_cursor(self.item_by_idx(kwargs["eprompt_idx_int"]))

    # rel-set-cursor will move the cursor relative to its current position.
    # unlike set-cursor, it will both not allow the selection to be set to None
    # by going off-list.

    @command_format("rel-set-cursor\s*(?P<prompt_relidx_int>[0-9-]+)?\s*$")
    @generic_parse_error
    def rel_set_cursor(self, **kwargs):
        idx = kwargs["prompt_relidx_int"]

        if self.sel:
            curidx = self.idx_by_item(self.sel)

        # curidx = -1 so that a `rel_set_cursor 1` (i.e. next) will 
        # select item 0
        else:
            curidx = -1

        item = self.item_by_idx(curidx + idx)
        if not item:
            log.info("Will not relative scroll out of list.")
        else:
            return self._set_cursor(item)

    def _set_cursor(self, item):
        global needs_redraw

        # May end up as None
        if item != self.sel:
            if self.sel:
                self.sel.unselect()

            self.sel = item

            if self.sel:
                self.sel.select()

                # If we have to adjust offset to 
                # keep selection on the screen,
                # refresh again.

                if self.offset > self.sel.max_offset:
                    self.offset = self.sel.max_offset
                elif self.offset < self.sel.min_offset:
                    self.offset = self.sel.min_offset

            self.refresh()
            needs_redraw = True

    def command(self, cmd):
        global needs_redraw

        log.debug("TagList command: %s" % cmd)
        if cmd == "page-down":
            self.offset = min(self.offset + (self.height - 1), self.max_offset)
            needs_redraw = True
        elif cmd == "page-up":
            self.offset = max(self.offset - (self.height - 1), 0)
            needs_redraw = True

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

    def refresh(self):
        self.max_offset = -1 * self.height
        idx = 0
        for tag in self.tags:
            ml = tag.refresh(self.width, idx)

            header, ml = ml[0], ml[1:]

            # Update each item's {min,max}_offset for being visible
            # in case they become selections.

            for i in xrange(len(tag)):
                curpos = self.max_offset + header + sum(ml[0:i + 1])
                tag[i].min_offset = max(curpos + 1, 0)
                tag[i].max_offset = curpos + (self.height - ml[i])

            self.max_offset += (header + sum(ml))
            idx += len(tag)

        # Ensure that calculated selected max offset
        # aren't outside of the general max offset

        if self.sel and self.sel.max_offset > self.max_offset:
            self.sel.max_offset = self.max_offset

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

            # Elif we're possible visible
            elif spent_lines >= self.offset:

                # If we're *entirely* visible, render the whole thing
                if spent_lines < ((self.offset + self.height) - taglines):
                    dest_start = (spent_lines - self.offset)
                    tag.pad.overwrite(self.pad, 0, 0, dest_start, 0,\
                            dest_start + taglines - 1 , self.width - 1)

                # Elif we're partially visible.
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

# The Screen class handles the layout of multiple sub-windows on the 
# main curses window. It's also the top-level gui object, so call to refresh the
# screen and get input should come through it.

class Screen():
    def init(self, user_queue, callbacks, layout = [[],[TagList],[InputBox]]):
        self.user_queue = user_queue
        self.callbacks = callbacks
        self.layout = layout

        if self.curses_setup() < 0:
            return -1

        self.input_box = None
        self.sub_edit = False

        self.subwindows()

        # Start grabbing user input
        self.start_input_thread()

    def curses_setup(self):
        self.stdscr = curses.initscr()

        # This can throw an exception, but we shouldn't care.
        try:
            curses.curs_set(0)
        except:
            pass

        try:
            curses.noecho()
            curses.start_color()
            curses.use_default_colors()
        except Exception, e:
            log.error("Curses setup failed: %s" % e.msg)
            return -1

        self.height, self.width = self.stdscr.getmaxyx()

        for i, c in enumerate([ 7, 4, 3 ]):
            curses.init_pair(i + 1, c, -1)

        return 0

    # Translate the layout into a set of curses pads given
    # a set of coordinates relating to how they're mapped to the screen.

    def subwindow(self, ct, top, left, width, height = -1):
        ci = ct()

        # This will grab the last inputbox instantiated,
        # though others seem pointless anyway.

        if ct == InputBox:
            self.input_box = ci

        # Top and bottom windows specify an absolute height
        # in their class (usually 1) and as such it doesn't
        # need to be specified here.

        if height < 0:
            height = ci.get_height()

        # Height - 1 because start + height = line after bottom.

        bottom = top + (height - 1)
        right = left + width

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

        return (ci, height)

    def subwindows(self):
        self.focused = None
        top = self.layout[0]
        top_h = 0
        if top:
            top_w = self.width / len(top)
        tops = []

        for i, c in enumerate(top):
            win_h, ci = self.subwindow(c, 0, i * top_w, top_w)
            top_h = max(top_h, win_h)
            tops.append((c, ci))

        bot = self.layout[2]
        bot_h = 0
        if bot:
            bot_w = self.width / len(bot)
        bots = []

        for i, c, in enumerate(bot):
            win_h = c().get_height()
            ci, h = self.subwindow(c, self.height - win_h, i * bot_w, bot_w)
            bot_h = max(bot_h, win_h)
            bots.append((c, ci))

        mid = self.layout[1]
        if mid:
            mid_w = self.width / len(mid)

        mids = []
        for i, c in enumerate(mid):
            ci, h = self.subwindow(c, top_h, mid_w * i, \
                    mid_w, self.height - bot_h)
            mids.append((c, ci))

        self.windows = ( tops, mids, bots )

        # Default to giving first taglist focus.
        self.focus("taglist", 0)

    def refresh_callback(self, c, t, l, b, r):
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

    def resize(self):
        try:
            curses.endwin()
        except:
            pass

        self.stdscr.refresh()
        self.curses_setup()
        self.subwindows()
        self.refresh()

    # Call refresh for all windows from
    # top to bottom, left to right.

    def refresh(self):
        for region in self.windows:
            for ct, c in region:
                c.refresh()
        curses.doupdate()

    def redraw(self):
        for region in self.windows:
            for ct, c in region:
                c.redraw()
        curses.doupdate()

    # Focus idx-th instance of cls.

    def focus(self, cls, idx):
        if cls == "taglist":
            targetct = TagList
        else:
            log.info("unknown window class: %s" % cls)

        curidx = 0

        for region in self.windows:
            for ct, c in region:
                if ct == targetct:
                    if curidx == idx:
                        log.debug("Focusing %s %d" % (cls, idx))
                        self.focused = c
                        break
                    curidx += 1
            else:
                continue
            break
        else:
            log.info("%s of idx %d not found" % (cls, idx))

    # Pass a command to focused window:

    def command(self, cmd):
        if cmd.startswith("focus "):
            rest = cmd[6:]
            if " " in rest:
                cls, idx = rest.split(" ", 1)
                try:
                    idx == int(idx)
                except:
                    log.info("Failed to parse index (\"%s\") as integer" % idx)
                    return
            else:
                cls = rest
                idx = 0

            self.focus(cls, idx)
        elif cmd == "resize":
            self.resize()

        # Propagate command to focused window
        else:
            self.focused.command(cmd)

    # Thread to put fully formed commands on the user_queue.

    def input_thread(self, binds = {}):
        global needs_redraw
        while True:
            r = self.input_box.pad.getch()

            # This should be handled by SIGWINCH
            if r == curses.KEY_RESIZE:
                continue

            # We're in an edit box
            if self.sub_edit:
                # Feed the key to the input_box
                rc = self.input_box.key(r)

                # If rc == 1, need more keys
                # If rc == 0, all done (result could still be "" though)
                if not rc:
                    self.sub_edit = False
                    self.input_done.set()
                continue

            # We're not in an edit box.

            # Convert to a writable character, if in the ASCII range
            if r < 256:
                r = chr(r)

            # Try to translate raw key to full command.
            if r in binds:
                self.user_queue.put(("CMD", binds[r]))

    def start_input_thread(self):
        self.input_done = Event()
        self.inthread =\
                Thread(target = self.input_thread,
                       args = [{ ":" : "command",
                                "e" : "toggle enumerated",
                                "q" : "quit",
                                "g" : "goto",
                                curses.KEY_NPAGE : "page-down",
                                curses.KEY_PPAGE : "page-up",
                                curses.KEY_DOWN : "rel-set-cursor 1",
                                curses.KEY_UP : "rel-set-cursor -1"}])

        self.inthread.daemon = True
        self.inthread.start()

    def exit(self):
        curses.endwin()

class CantoCursesGui():
    def init(self, backend, do_curses=True):
        self.backend = backend

        # Tweakables that affect the overall operation.
        self.tweakables = {
            "enumerated" : False,
        }

        callbacks = {
                "set_tweakable" : self.set_tweakable_callback,
                "get_tweakable" : self.get_tweakable_callback,
                "write" : self.backend.write
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

        for tag in alltags:
            for item in r[1][tag.tag]:
                tag.append(item)

        # Initial story attribute populate.

        attribute_stories = {}

        for tag in alltags:
            for story in tag:
                attribute_stories[story.id] = story.needed_attributes()

        self.backend.write("ATTRIBUTES", attribute_stories)
        r = self.wait_response("ATTRIBUTES")

        for tag in alltags:
            for story in tag:
                for k in r[1][story.id]:
                    a = r[1][story.id][k]
                    if type(a) == unicode:
                        story.content[k] = a.replace("%", "\\%")
                    else:
                        story.content[k] = a

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

    # Set a tweakable *only* if there is a value already.
    # This means that every tweakable has to have a default
    # (of course), but also that tweakables can't be randomly
    # added by accident.

    def set_tweakable_callback(self, tweak, value):
        changed = False
        if tweak in self.tweakables:
            if self.tweakables[tweak] != value:
                self.tweakables[tweak] = value
                changed = True
        else:
            log.info("Unknown tweakable: %s" % tweak)
            return

        # Special actions on certain tweakables changed.
        if changed:
            if tweak == "enumerated":
                self.screen.refresh()

    def get_tweakable_callback(self, tweak):
        if tweak in self.tweakables:
            return self.tweakables[tweak]
        return None

    def winch(self):
        self.backend.responses.put(("CMD", "resize"))

    def run(self):
        global needs_refresh
        global needs_redraw

        while True:

            cmd = self.backend.responses.get()

            # User command
            if cmd[0] == "CMD":
                log.debug("CMD: %s" % cmd[1])

                # Sub in a user command on the fly.
                if cmd[1] == "command":
                    cmd = (cmd[0], self.screen.input_callback(":"))

                if cmd[1] in ["quit", "exit"]:
                    self.screen.exit()
                    self.backend.exit()
                    return

                # Tweakable Operations
                elif cmd[1].startswith("set "):
                    rest = cmd[1][4:]
                    self.set_tweakable_callback(rest, True)
                elif cmd[1].startswith("unset "):
                    rest = cmd[1][6:]
                    self.set_tweakable_callback(rest, False)
                elif cmd[1].startswith("toggle "):
                    rest = cmd[1][7:]
                    t = self.get_tweakable_callback(rest)
                    self.set_tweakable_callback(rest, not t)

                # Propagate command to screen / subwindows
                elif cmd[1] != "noop":
                    self.screen.command(cmd[1])

            # XXX Server notification/reply

            if needs_refresh:
                self.screen.refresh()
                needs_refresh = False
                needs_redraw = False
            elif needs_redraw:
                self.screen.redraw()
                needs_redraw = False
