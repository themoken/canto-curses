#!/usr/bin/python
# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto.encoding import encoder
from theme import theme_print, theme_len

import logging

log = logging.getLogger("GUI")

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
        log.debug("header: %s (%d)" % (header, lheader))
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
    def __init__(self, pad):
        self.pad = pad

        if not curtags:
            self.tags = alltags
        else:
            self.tags = curtags

    def refresh(self):
        self.pad.erase()
        for i, tag in enumerate(self.tags):
            tag.refresh(self.pad)

# The Screen class handles the layout of multiple sub-windows on the 
# main curses window. It's also the top-level gui object, so call to refresh the
# screen and get input should come through it.

class Screen():
    def init(self, layout = [[],[TagList],[]]):
        self.layout = layout

        if self.curses_setup() < 0:
            return -1

        self.subwindows()
        self.refresh()

    def curses_setup(self):
        self.stdscr = curses.initscr()
        self.stdscr.nodelay(1)

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

    def subwindows(self):
        top = self.layout[0]
        top_h = 0
        tops = []
        # XXX : top stuff

        bot = self.layout[2]
        bot_h = 0
        bots = []
        # XXX : bot stuff

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

            mids.append((
                c(pad),                     # class
                top_h,                      # top
                mid_w * i,                  # left
                self.height - bot_h - 1,    # bottom
                (mid_w * (i + 1)) - 1       # right
                ))

        self.windows = ( tops, mids, bots )

    def refresh(self):
        for region in self.windows:
            for c, t, l, b, r in region:
                c.refresh()
                c.pad.noutrefresh(0, 0, t, l, b, r)
        curses.doupdate()

class CantoCursesGui():
    def init(self, backend, do_curses=True):
        self.backend = backend

        self.backend.write("LISTFEEDS", u"")
        self.wait_response("LISTFEEDS")

        log.debug("RESPONSES: %s" % backend.responses)
        self.tracked_feeds = backend.responses[0][1]
        self.next_response()

        # Initial tag populate.

        item_tags = []
        for tag, URL in self.tracked_feeds:
            log.info("Tracking [%s] (%s)" % (tag, URL))
            t = Tag(tag)
            item_tags.append(tag)

        self.backend.write("ITEMS", item_tags)
        self.wait_response("ITEMS")

        for tag in alltags:
            for item in self.backend.responses[0][1][tag.tag]:
                tag.add(item)

        # Initial story attribute populate.

        attribute_stories = {}

        for tag in alltags:
            for story in tag:
                attribute_stories[story.id] = story.needed_attributes()

        self.backend.write("ATTRIBUTES", attribute_stories)
        self.wait_response("ATTRIBUTES")

        for tag in alltags:
            for story in tag:
                for k in self.backend.responses[0][1][story.id]:
                    story.content[k] =\
                        self.backend.responses[0][1][story.id][k]

        # Short circuit for testing the above setup.
        if do_curses:
            log.debug("Starting curses.")
            self.screen = Screen()
            self.screen.init()

    def next_response(self):
        if self.backend.responses:
            log.debug("DISCARD: %s" % (self.backend.responses[0],))
            self.backend.response_lock.acquire()
            r = self.backend.responses[0]
            self.backend.responses = self.backend.responses[1:]
            self.backend.response_lock.release()
            return r
        return None

    def wait_response(self, cmd):
        log.debug("waiting on %s" % cmd)
        while True:
            if self.backend.responses:
                if self.backend.responses[0][0] == cmd:
                    break
                log.debug("waiting: %s != %s" % 
                        (self.backend.responses[0][0], cmd))

                # Ignore other output.
                self.next_response()
        log.debug("not waiting on %s anymore" % cmd)

    def run(self):
        time.sleep(0.01)
