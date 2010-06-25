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

class Tests(unittest.TestCase):

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
