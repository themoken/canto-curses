#!/usr/bin/env python
# -*- coding: utf-8 -*-

#Canto - RSS reader backend
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

import tests.main
import tests.gui

import logging

logging.basicConfig(
    filemode = "w",
    format = "%(asctime)s : %(name)s -> %(message)s",
    datefmt = "%H:%M:%S",
    level = logging.DEBUG
)

import unittest
import sys

all_modules = {
        "main" : tests.main.Tests ,
        "gui" : tests.gui.Tests }

all_tests = {
        "test_args" : tests.main.Tests,
        "test_start_daemon" : tests.main.Tests,
        "test_ensure_files" : tests.main.Tests,
        "test_next_response_goodlock" : tests.gui.Tests,
        "test_next_response_badlock" : tests.gui.Tests,
}

if __name__ == "__main__":
    t = []
    if len(sys.argv) == 1:
        for key in all_tests:
            t.append(all_tests[key](key))
    else:
        for arg in sys.argv[1:]:
            if arg in all_tests:
                t.append(all_tests[arg](arg))
            elif arg in all_modules:
                for k in all_tests:
                    if all_tests[k] == all_modules[arg]:
                        t.append(all_tests[k](k))
            else:
                print "Unknown arg: %s" % arg

    suite = unittest.TestSuite()
    suite.addTests(t)
    unittest.TextTestRunner(verbosity=2).run(suite)
