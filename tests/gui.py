# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_curses.main import CantoCurses
from canto_curses.gui import CantoCursesGui, alltags

from threading import Thread, Lock
import unittest
import time
import os

class FakeLock():
    def acquire(self):
        pass

    def release(self):
        pass

class Tests(unittest.TestCase):

    def hold_lock(self, ccurses):
        for i in xrange(1000):
            ccurses.response_lock.acquire()
            ccurses.responses.append(("ITEMS", "%d" % i))
            ccurses.response_lock.release()

    # This might a pretty poor test, as all race condition tests
    # end up being (i.e. not immune to false positives by the nature of the
    # problem). I can say that with a FakeLock() I generally get corrupted
    # output anywhere between 0 and 110 tries, so I made 150 iterations
    # my test.

    def __test_next_response(self, lock):
        c = CantoCurses()
        g = CantoCursesGui()
        c.response_lock = lock
        g.backend = c

        # Make sure empty list doesn't matter
        g.backend.responses = []
        g.next_response()

        t = Thread(target=self.hold_lock, args=(c,))
        t.start()

        discards = []

        while t.isAlive():
            r = g.next_response()
            if r:
                print r
                discards.append(r)

        t.join()

        # Ensure that we didn't lose anything
        self.assertTrue(len(discards) + len(g.backend.responses) == 1000)

        # Ensure that we discarded in order
        for i, d in enumerate(discards):
            self.assertTrue(d == ("ITEMS", "%d" % i))

        # Ensure remaining responses are in order
        for i, d in enumerate(g.backend.responses):
            i += len(discards)
            self.assertTrue(d == ("ITEMS", "%d" % i))

    def test_next_response_goodlock(self):
        for i in xrange(150):
            self.__test_next_response(Lock())

    def test_next_response_badlock(self):
        gen = 0;
        try:
            for i in xrange(1000):
                gen = i
                self.__test_next_response(FakeLock())
        except:
            print "Got race in gen %d" % gen
            return

        print "WARNING: No race with badlock"

    def test_wait_response(self):
        c = CantoCurses()
        g = CantoCursesGui()

        # Miniature init
        c.response_lock = Lock()
        g.backend = c
        g.backend.responses = [("RESP1", "a"),("RESP2", "b"),("RESP3", "c")]

        # Ensure if it's the first response, others are undisturbed.
        g.wait_response("RESP1")
        self.assertTrue(g.backend.responses == [("RESP1", "a"),
                                                ("RESP2", "b"),
                                                ("RESP3", "c")])

        # Ensure one gets discarded, other is untouched.
        g.wait_response("RESP2")
        self.assertTrue(g.backend.responses == [("RESP2", "b"),
                                                ("RESP3", "c")])

    def test_init_gui(self):
        c = CantoCurses()

        # Set args, don't handle log.
        c.init(["-D", os.getenv("PWD") + "/tests/basic_dir"], False)

        # Start real response thread.
        c.start_thread()

        g = CantoCursesGui()

        # Init, but don't start curses.
        g.init(c, False)

        # Simple helper to get specific tag from list
        def get_tag(tag):
            for t in alltags:
                if t.tag == tag:
                    return list(t)
            return None

        self.assertTrue(len(alltags) == 2)
        self.assertTrue(len(g.tracked_feeds) == 2)
        self.assertTrue(get_tag("Test 1"))
        self.assertTrue(get_tag("Test 2"))
        self.assertTrue(len(get_tag("Test 1")) == 1)
        self.assertTrue(len(get_tag("Test 2")) == 1)
        self.assertTrue(get_tag("Test 1")[0].content["title"] == "Item 1")
        self.assertTrue(get_tag("Test 1")[0].content["link"] ==
                "http://example.com/item/1")
        self.assertTrue(get_tag("Test 2")[0].content["title"] == "Item 1")
        self.assertTrue(get_tag("Test 2")[0].content["link"] ==
                "http://example.com/item/1")

        # Kill daemon.
        g.backend.write("DIE", "")
