# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto.encoding import encoder
from theme import theme_print, theme_len
from input import InputBox
from consts import *

import logging

log = logging.getLogger("GUI")

from threading import Thread
from Queue import Queue
import curses
import time

class Story():
    def __init__(self, id):
        self.content = {}
        self.id = id

    def __str__(self):
        return "%3" + self.content["title"] + "%0"

    # Return what attributes of this story are needed
    # to render it. Eventually this will be determined
    # on the client render string.

    def needed_attributes(self):
        return [ "title", "link" ]

curtags = []
alltags = []

class Tag(set):
    def __init__(self, tag):
        self.tag = tag
        alltags.append(self)

    # Create Story from ID before adding to set.

    def add(self, id):
        s = Story(id)
        set.add(self, s)

    def refresh(self, pad):
        mheight, mwidth = pad.getmaxyx()

        left = u"%8│%0 "
        left_more = u"%8│%0     "
        right = u" %8│%0"

        header = self.tag + u"\n"
        lheader = theme_len(header)
        theme_print(pad, header, lheader)

        for item in self:
            try:
                s = "%s" % item
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
                        pad.addch(' ')

                    # Right border
                    theme_print(pad, right, rlen)
                    lines += 1

            except Exception, e:
                log.error("addstr excepted: %s" % (e, ))

# TagList is the class renders a classical Canto list of tags into the given
# panel. It defers to the Tag class for the actual individual tag rendering.

class TagList():
    def init(self, pad, refresh_callback, coords):
        self.pad = pad
        self.refresh_callback = refresh_callback

        if not curtags:
            self.tags = alltags
        else:
            self.tags = curtags

        self.coords = coords

    def key_pad(self):
        return False

    def refresh(self):
        self.pad.erase()
        for i, tag in enumerate(self.tags):
            tag.refresh(self.pad)
        self.refresh_callback(self.coords)

# The Screen class handles the layout of multiple sub-windows on the 
# main curses window. It's also the top-level gui object, so call to refresh the
# screen and get input should come through it.

class Screen():
    def init(self, layout = [[],[TagList],[InputBox]]):
        self.layout = layout

        if self.curses_setup() < 0:
            return -1

        self.input_box = None
        self.subwindows()

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

        for i in xrange(curses.COLORS):
            curses.init_pair(i + 1, i, -1)

        return 0

    # Translate the layout into a set of curses pads given
    # a set of coordinates relating to how they're mapped to the screen.

    # XXX : This code can probably be expressed much more concisely

    def subwindows(self):
        top = self.layout[0]
        top_h = 0
        tops = []

        # XXX : top stuff

        bot = self.layout[2]
        bot_w = self.width / len(bot)
        bot_h = 0
        bots = []

        for i, c, in enumerate(bot):
            ci = c()
            if c == InputBox:
                self.input_box = ci

            bot_h = max(bot_h, ci.get_height())

            pad = curses.newpad(bot_h + 1, bot_w)
            coords =\
            (
                ci,                         # class
                (self.height - bot_h),      # top
                bot_w * i,                  # left
                self.height - 1,            # bottom
                (bot_w * (i + 1)) - 1       # right
            )

            bots.append(coords)
            ci.init(pad, self.refresh_callback, coords)

        mid = self.layout[1]
        mid_w = self.width / len(mid)
        mid_h = self.height - (top_h + bot_h)

        mids = []
        for i, c in enumerate(mid):

            # height + 1 to workaround legacy curses windows' bottom right
            # corner being unwritable.

            pad = curses.newpad(mid_h + 1, mid_w)

            # Add ( instantiated class, top, left, bottom, right )
            # That is, controlling class and main screen coordinates
            # for noutrefresh()

            ci = c()
            if c == InputBox:
                self.input_box = ci

            coords =\
            (
                ci,                         # class
                top_h,                      # top
                mid_w * i,                  # left
                self.height - bot_h - 1,    # bottom
                (mid_w * (i + 1)) - 1       # right
            )

            mids.append(coords)
            ci.init(pad, self.refresh_callback, coords)

        self.windows = ( tops, mids, bots )

    # We make this a callback because
    #   a ) the subwindow knows best when its content
    #       actually needs to be re-rendered
    #
    #   b ) it's advantageous for thing like InputBox
    #       to be able to redraw and curses.doupdate()
    #       itself without breaking back into the main
    #       control loop.

    def refresh_callback(self, coords):
        c, t, l, b, r = coords
        c.pad.noutrefresh(0, 0, t, l, b, r)

    # Call refresh for all windows from
    # top to bottom, left to right.

    def refresh(self):
        for region in self.windows:
            for c, t, l, b, r in region:
                c.refresh()
        curses.doupdate()

    # Thread to put fully formed commands on the user_queue.

    def input_thread(self, user_queue, binds = {}):
        while self.input_box:
            r = self.input_box.pad.getch()
            if r < 256:
                r = chr(r)

            if r in binds:
                r = binds[r]
                if r == "command":
                    r = self.input_box.edit()
                user_queue.put(r)
                self.input_box.reset()

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

            self.user_queue = Queue()
            self.input_thread =\
                    Thread(target = self.screen.input_thread,
                           args = (self.user_queue, { ":" : "command",
                                                      "q" : "quit" }))
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
        if not self.user_queue.empty():
            cmd = self.user_queue.get()
            log.debug("CMD: %s" % cmd)
            if cmd in ["quit", "exit"]:
                self.screen.exit()
                return GUI_EXIT

        self.screen.refresh()
