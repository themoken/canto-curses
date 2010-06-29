# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto.encoding import encoder
from utility import silentfork
from theme import theme_print, theme_len, WrapPad, FakePad
from input import InputBox
from consts import *

import logging

log = logging.getLogger("GUI")

from threading import Thread, Event
from Queue import Queue
import curses
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

    def enumeration_prefix(self, idx):
        return "%2[" + str(idx) + "]%0 "

    def render(self, idx = 0):
        return "%2" + self.content["title"] + "%0"

    # Return what attributes of this story are needed
    # to render it. Eventually this will be determined
    # on the client render string.

    def needed_attributes(self):
        return [ "title", "link" ]

class Tag(set):
    def __init__(self, tag, callbacks):
        # Note that Tag() is only given the top-level CantoCursesGui
        # callbacks as it shouldn't be doing input / refreshing
        # itself.

        self.callbacks = callbacks
        self.tag = tag
        alltags.append(self)

    # Create Story from ID before adding to set.

    def add(self, id):
        s = Story(id, self.callbacks)
        set.add(self, s)

    def refresh(self, mwidth, idx_offset):
        # Render once, doing no I/O to get proper dimensions

        # We force enumerated = 0 on this run so we know
        # the correct number of lines to truncate enumerated lines
        # on the next call, because the number of lines shouldn't
        # be different ... although a future tweakable should let
        # user initiated enumeration shift lines, but automatically
        # initiated enumeration not.

        height = self.render(mwidth, FakePad(mwidth), idx_offset, 0)[1]

        # Create a custom pad
        self.pad = curses.newpad(height, mwidth)

        # Render again, actually drawing to the screen,
        # return ( new idx_offset, display lines for tag)
        enumerated = self.callbacks["get_tweakable"]("enumerated")
        return self.render(mwidth, WrapPad(self.pad), idx_offset, enumerated)

    def render(self, mwidth, pad, idx_offset, enumerated):

        left = u"%1│%0 "
        left_more = u"%1│%0     "
        right = u" %1│%0"

        header = self.tag + u"\n"
        lheader = theme_len(header)
        theme_print(pad, header, lheader)
        tag_lines = 1

        for i, item in enumerate(self):
            try:
                s = item.render(idx_offset)
                if enumerated:
                    s = item.enumeration_prefix(idx_offset) + s

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

                        for i in xrange(3):
                            pad.waddch('.')

                        # Render no more.
                        s = None

                    # Spacer for right border
                    while pad.getyx()[1] < (mwidth - rlen):
                        pad.waddch(' ')

                    # Right border
                    theme_print(pad, right, rlen)

                    # Keep track of lines for this item
                    lines += 1

                    # Keep track of total lines for this tag
                    tag_lines += 1

                if not enumerated:
                    item.unenumerated_lines = lines

                # Keep track of global index
                idx_offset += 1

            except Exception, e:
                log.error("addstr excepted: %s" % (e, ))

        # Returns new global index offset and number of screen lines taken.
        return (idx_offset, tag_lines)

# TagList is the class renders a classical Canto list of tags into the given
# panel. It defers to the Tag class for the actual individual tag rendering.

class TagList():
    def init(self, pad, callbacks):
        # Drawing information
        self.pad = pad
        self.height, self.width = self.pad.getmaxyx()
        self.offset = 0

        # Callback information
        self.callbacks = callbacks

        # Tags to be displayed.
        if not curtags:
            self.tags = alltags
        else:
            self.tags = curtags

    def lookup_by_idx(self, idx):
        spent = 0
        for tag in self.tags:
            ltag = len(tag)
            if spent + ltag > idx:
                return list(tag)[ idx - spent ]
            spent += ltag
        return None

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
            if " " not in cmd:
                # Ensure the items are enumerated for goto
                t = self.callbacks["get_tweakable"]("enumerated")
                self.callbacks["set_tweakable"]("enumerated", True)

                target = self.callbacks["input"]("goto: ")

                # Reset enumerated to previous value
                self.callbacks["set_tweakable"]("enumerated", t)
            else:
                target = cmd.split(" ", 1)[1]

            try:
                target = int(target)
            except:
                log.error("Can't parse %s as integer" % target)
                return

            item = self.lookup_by_idx(target)
            if not item:
                log.debug("No item with idx %d found." % target)
                return

            silentfork(None, item.content["link"])

    def refresh(self):
        self.max_offset = -1 * self.height
        idx = 0
        for tag in self.tags:
            idx, lines = tag.refresh(self.width, idx)
            self.max_offset += lines
        self.redraw()

    def redraw(self):
        self.pad.erase()

        spent_lines = 0
        lines = self.height

        for tag in self.tags:
            taglines = tag.pad.getmaxyx()[0]

            l = self.offset - spent_lines

            # If we're still off screen up after last tag, but this
            # tag will put us over the top, partial render.

            if spent_lines < self.offset and\
                    taglines > (self.offset - spent_lines):
                start = (self.offset - spent_lines)

                # min() so we don't try to write too much if the
                # first tag is also the only tag on screen.
                maxr = min(taglines - start, self.height)

                try:
                    tag.pad.overwrite(self.pad, start, 0, 0, 0,\
                            maxr - 1, self.width - 1)
                except Exception, e:
                    log.error("Partial top overwrite exception! %s" % (e,))
                    log.error("particulars: start -> %d" % start)
                    log.error("             maxr  -> %d" % maxr)
                    log.error("             width -> %d" % self.width)
                    log.error("             height-> %d" % self.height)
                    log.error("             offset-> %d" % self.offset)

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
        self.focused = None

        if self.curses_setup() < 0:
            return -1

        self.input_box = None
        self.sub_edit = False

        self.subwindows()

        # Default to giving first taglist focus.
        self.focus("taglist", 0)

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

        for i, c in enumerate([ 7, 4 ]):
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

        # Propagate command to focused window
        else:
            self.focused.command(cmd)

    # Thread to put fully formed commands on the user_queue.

    def input_thread(self, binds = {}):
        global needs_redraw
        while True:
            r = self.input_box.pad.getch()

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
                                curses.KEY_PPAGE : "page-up" }])

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
                "get_tweakable" : self.get_tweakable_callback
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
                tag.add(item)

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
                    story.content[k] =\
                        r[1][story.id][k]

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

    def run(self):
        global needs_refresh
        global needs_redraw

        cmd = self.backend.responses.get()

        # User command
        if cmd[0] == "CMD":
            log.debug("CMD: %s" % cmd[1])

            # Sub in a user command on the fly.
            if cmd[1] == "command":
                cmd = (cmd[0], self.screen.input_callback(":"))

            if cmd[1] in ["quit", "exit"]:
                self.screen.exit()
                return GUI_EXIT

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
