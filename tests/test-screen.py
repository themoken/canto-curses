#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys

sys.modules['curses'] = __import__("fake_curses")
sys.modules['canto_curses.widecurse'] = __import__("fake_widecurse")

import curses

from base import *

from canto_curses.main import CANTO_PROTOCOL_COMPATIBLE
from canto_curses.config import config
from canto_curses.tagcore import tag_updater
from canto_curses.gui import CantoCursesGui # to Screen to curses

from canto_next.hooks import on_hook, call_hook

class TestScreen(Test):
    def wait_on_update(self):
        while config.vars["needs_refresh"] or\
                config.vars["needs_redraw"] or\
                config.vars["needs_resize"]:
            time.sleep(0.1)

    def compare_output(self, backend, evalue):
        if backend.output[-1] != evalue:
            raise Exception("Unexpected output - %s\n\nWanted %s" % (backend.output[-1], evalue))

    def check(self):
        config_script = {
            'VERSION' : { '*' : [('VERSION', CANTO_PROTOCOL_COMPATIBLE)] },
            'CONFIGS' : { '*' : [('CONFIGS', { "CantoCurses" : config.template_config })] },
                
        }

        config_backend = TestBackend("config", config_script)

        config.init(config_backend, CANTO_PROTOCOL_COMPATIBLE)

        config_backend.inject("NEWTAGS", [ "maintag:Tag(0)", "maintag:Tag(1)" ])

        tagcore_script = generate_item_script(2, 5, "maintag:Tag(%d)", "Story(%d,%d)",
                { "title" : "%d,%d - title", "link" : "http://example.com/%d/%d",
                    "description" : "Description(%d,%d)", "canto-tags" : "",
                    "canto-state" : "" }
        ) 

        tag_backend = TestBackend("tagcore", tagcore_script)

        tag_updater.init(tag_backend)
        tag_updater.update()

        curses_script = {}

        curses_backend = TestBackend("curses", curses_script)

        start = time.time()

        gui = CantoCursesGui(curses_backend)

        self.wait_on_update()

        gui.issue_cmd("color 8 black black")

        self.compare_output(config_backend, ('SETCONFIGS', {'CantoCurses': {'color': {'8': {'bg': 0, 'fg': 0}}}}))

        if curses.pairs[8] != [ 0, 0 ]:
            raise Exception("Pair not immediately honored! %s" % curses.pairs[8])

        # Default loadout is input_box, taglist
        taglist = gui.screen.windows[1]

        return True

TestScreen("screen")
