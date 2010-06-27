# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto.encoding import encoder
from theme import theme_print, theme_len, WrapPad, FakePad
from input import InputBox
from consts import *

import logging

log = logging.getLogger("GUI")

from threading import Thread
from Queue import Queue
import curses
import time

# Globals
# Yes, I know, this is Python.

curtags = []
alltags = []

needs_refresh = False
needs_redraw = False

# Tweakables represent the GUI
# values that can be changed using
# set/unset/toggle from the command line.

tweakables = {
    "enumerated" : False,
}

class Story():
    def __init__(self, id):
        self.content = {}
        self.id = id

    def render(self, idx = 0):
        body = "%2" + self.content["title"] + "%0"
        if tweakables["enumerated"]:
            body = "%2[" + str(idx) + "]%0 " + body
        return body

    # Return what attributes of this story are needed
    # to render it. Eventually this will be determined
    # on the client render string.

    def needed_attributes(self):
        return [ "title", "link" ]

class Tag(set):
    def __init__(self, tag):
        self.tag = tag
        alltags.append(self)

    # Create Story from ID before adding to set.

    def add(self, id):
        s = Story(id)
        set.add(self, s)

    def refresh(self, mwidth, idx_offset):
        # Render once, doing no I/O to get proper dimensions
        height = self.render(mwidth, FakePad(), idx_offset)[1]

        # Create a custom pad
        self.pad = curses.newpad(height, mwidth)

        # Render again, actually drawing to the screen,
        # return ( new idx_offset, display lines for tag)
        return self.render(mwidth, WrapPad(self.pad), idx_offset)

    def render(self, mwidth, pad, idx_offset):

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

                    # Spacer for right border
                    while pad.getyx()[1] < (mwidth - rlen):
                        pad.waddch(' ')

                    # Right border
                    theme_print(pad, right, rlen)

                    # Keep track of lines for this item
                    lines += 1

                    # Keep track of total lines for this tag
                    tag_lines += 1

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
            if " " in cmd:
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

                log.debug("Would go to %s" % item.content["link"])

    # Render all 

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
                maxr = taglines - start
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
    def init(self, layout = [[],[TagList],[InputBox]]):
        self.layout = layout
        self.focused = None

        if self.curses_setup() < 0:
            return -1

        self.input_box = None
        self.subwindows()

        # Default to giving first taglist focus.
        self.focus("taglist", 0)

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

        callbacks = {}
        callbacks["refresh"] = refcb
        callbacks["input"] = self.input_callback

        # XXX build callbacks

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
        log.debug("t, l, b, r -> %d, %d, %d, %d" % (t, l, b, r))
        c.pad.noutrefresh(0, 0, t, l, b, r)

    def input_callback(self, prompt):
        return self.input_box.edit(prompt)

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

    def input_thread(self, user_queue, binds = {}):
        global needs_redraw
        while self.input_box:
            r = self.input_box.pad.getch()
            if r < 256:
                r = chr(r)

            if r in binds:
                r = binds[r]
                if r == "command":
                    r = self.input_box.edit()

                    # Cancelled user input
                    if not r:
                        r = "noop"

                user_queue.put(("CMD", r))
                self.input_box.reset()
                needs_redraw = True

    def exit(self):
        curses.endwin()

class CantoCursesGui():
    def init(self, backend, do_curses=True):
        self.backend = backend

        self.backend.write("LISTFEEDS", u"")
        r = self.wait_response("LISTFEEDS")
        self.tracked_feeds = r[1]

        # Initial tag populate.

        item_tags = []
        for tag, URL in self.tracked_feeds:
            log.info("Tracking [%s] (%s)" % (tag, URL))
            t = Tag(tag)
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
            self.screen.init()
            self.screen.refresh()

            self.input_thread =\
                    Thread(target = self.screen.input_thread,
                           args = (self.backend.responses,
                               { ":" : "command",
                                 "e" : "toggle enumerated",
                                 "q" : "quit",
                                 curses.KEY_NPAGE : "page-down",
                                 curses.KEY_PPAGE : "page-up"}))

            self.input_thread.daemon = True
            self.input_thread.start()

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

    def run(self):
        global needs_refresh
        global needs_redraw

        cmd = self.backend.responses.get()

        # User command
        if cmd[0] == "CMD":
            log.debug("CMD: %s" % cmd[1])
            if cmd[1] in ["quit", "exit"]:
                self.screen.exit()
                return GUI_EXIT
            elif cmd[1].startswith("set "):
                needs_refresh = True
                rest = cmd[1][4:]
                if rest in tweakables:
                    tweakables[rest] = True
            elif cmd[1].startswith("unset "):
                needs_refresh = True
                rest = cmd[1][6:]
                if rest in tweakables:
                    tweakables[rest] = False
            elif cmd[1].startswith("toggle "):
                needs_refresh = True
                rest = cmd[1][7:]
                if rest in tweakables:
                    tweakables[rest] = not tweakables[rest]
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
