# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_curses.main import CantoCurses
from canto.client import CantoClient

import unittest
import signal
import os

class Tests(unittest.TestCase):

    def test_args(self):
        b = CantoCurses()

        # Test no arguments
        b.args([])
        self.assertEqual(b.conf_dir, os.getenv("HOME") + "/.canto-ng/")
        self.assertEqual(type(b.conf_dir), unicode)

        # Test -D initial directory setup
        b.args(["-D", "/some/path/somewhere"])
        self.assertEqual(b.conf_dir, "/some/path/somewhere")
        self.assertEqual(type(b.conf_dir), unicode)

    def test_start_daemon(self):
        b = CantoCurses()
        d = os.getenv("PWD") + "/tests/basic_dir"
        s = d + "/.canto_socket"

        if os.path.exists(s):
            os.remove(s)

        b.args(["-D", d])
        pid = b.start_daemon()
        print "Forked: %d" % pid

        # Actually connect to the socket. If
        # there isn't a daemon running on it,
        # ECONNREFUSED exception will fail the test.
        CantoClient.__init__(b, s)

        # Don't leave it hanging around for no reason.
        b.write("DIE", "")
        while not b.hupped: b.read()

    def test_ensure_files(self):
        b = CantoCurses()
        good = os.getenv("PWD") + "/tests/perms/good"
        bad = os.getenv("PWD") + "/tests/perms/bad"

        b.args(["-D", good])
        self.assertEqual(b.ensure_files(), None)

        b = CantoCurses()
        b.args(["-D", bad])
        self.assertEqual(b.ensure_files(), -1)
