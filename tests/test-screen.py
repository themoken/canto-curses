#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys

sys.modules['curses'] = __import__("fake_curses")
sys.modules['canto_curses.widecurse'] = __import__("fake_widecurse")

import curses

from base import *

from canto_curses.main import CANTO_PROTOCOL_COMPATIBLE
from canto_curses.config import config
from canto_curses.tagcore import tag_updater, alltagcores
from canto_curses.gui import CantoCursesGui # to Screen to curses
from canto_curses.locks import sync_lock
from canto_curses.taglist import TagList

from canto_next.hooks import on_hook, call_hook

import time

class TestScreen(Test):
    def __init__(self, name):
        config_script = {
            'VERSION' : { '*' : [('VERSION', CANTO_PROTOCOL_COMPATIBLE)] },
            'CONFIGS' : { '*' : [('CONFIGS', { "CantoCurses" : config.template_config })] },
                
        }

        self.config_backend = TestBackend("config", config_script)

        config.init(self.config_backend, CANTO_PROTOCOL_COMPATIBLE)

        self.config_backend.inject("NEWTAGS", [ "maintag:Tag(0)", "maintag:Tag(1)", "maintag:Tag(2)" ])

        tagcore_script = generate_item_script(3, 20, "maintag:Tag(%d)", "Story(%d,%d)",
                { "title" : "%d,%d - title", "link" : "http://example.com/%d/%d",
                    "description" : "Description(%d,%d)", "canto-tags" : "",
                    "canto-state" : "" }
        ) 

        self.tag_backend = TestBackend("tagcore", tagcore_script)

        tag_updater.init(self.tag_backend)

        # The standard opening of c-c, the tags can be in any state, but for the
        # purposes of testing, we want to make sure that the tagcores are in a known
        # state or the rest of this stuff will be racy.

        # Fortunately the real-world opening case is tested every time you run c-c =P

        # 9 = 3 tags * 3 responses per ITEMS call (ITEMS, ITEMSDONE, and ATTRIBUTES)

        while len(self.tag_backend.procd) != 9:
            print("len: %s" % len(self.tag_backend.procd))
            time.sleep(0.1)

        if len(alltagcores) != 3:
            raise Exception("Didn't get all tags!")
        if len(alltagcores[0]) != 20:
            raise Exception("Didn't get all items in tagcore[0]")
        if len(alltagcores[1]) != 20:
            raise Exception("Didn't get all items in tagcore[1]")

        gui_script = {}

        self.gui_backend = TestBackend("gui", gui_script)

        self.gui = CantoCursesGui(self.gui_backend)
        self.wait_on_update()

        Test.__init__(self, name)

    def wait_on_update(self):
        while True:
            ref = config.vars["needs_refresh"]
            red = config.vars["needs_redraw"]
            res = config.vars["needs_resize"]
            print("ref red res - %s %s %s" % (ref, red, res))
            if not (ref or red or res):
                return
            time.sleep(0.1)

    def compare_output(self, backend, evalue):
        if backend.output[-1] != evalue:
            raise Exception("Unexpected output - %s\n\nWanted %s" % (backend.output[-1], evalue))

    # This is all about making sure that all of the items that are referenced
    # in this list belong there, and are properly setup.

    def check_taglist_obj(self, taglist, target_object, recurse_attr=""):
        if not target_object:
            print("Checking None")
            return

        summary = self._summarize_object(target_object)
        print("Checking %s" % summary)

        if target_object == config.vars["selected"] and not target_object.selected:
            raise Exception("Object %s should know it's selected" % summary)
        if target_object.selected and config.vars["selected"] != target_object:
            raise Exception("Object %s thinks it's selected" % summary)

        if target_object.is_tag:
            if target_object.tag not in config.vars["curtags"]:
                raise Exception("Tag %s not in curtags!" % summary)
            if target_object not in taglist.tags:
                raise Exception("Tag %s not in taglist.tags!" % summary)
        else:
            if target_object not in target_object.parent_tag:
                raise Exception("Story %s not in parent tag!" % summary)
            if target_object.parent_tag.tag not in config.vars["curtags"]:
                raise Exception("Story %s tag not in curtags!" % summary)
            if target_object.id not in target_object.parent_tag.tagcore:
                raise Exception("Story %s not in tagcore!" % summary)
            if target_object.parent_tag not in taglist.tags:
                raise Exception("Story %s parent tag not in taglist.tags!")

        if recurse_attr:
            self.check_taglist_obj(taglist, getattr(target_object, recurse_attr), recurse_attr)

    def check_taglist_obj_links(self, taglist, target_object):
        self.check_taglist_obj(taglist, target_object, "next_obj")
        self.check_taglist_obj(taglist, target_object, "prev_obj")
        self.check_taglist_obj(taglist, target_object, "next_story")
        self.check_taglist_obj(taglist, target_object, "prev_story")
        self.check_taglist_obj(taglist, target_object, "next_sel")
        self.check_taglist_obj(taglist, target_object, "prev_sel")

    def get_taglist(self):
        return self.gui.screen.windows[self.gui.screen.window_types.index(TagList)]

    def check_taglist(self):
        sync_lock.acquire_write()

        taglist = self.get_taglist()
        self.check_taglist_obj_links(taglist, config.vars["target_obj"])
        self.check_taglist_obj_links(taglist, config.vars["selected"])
        self.check_taglist_obj_links(taglist, taglist.first_sel)
        self.check_taglist_obj_links(taglist, taglist.first_story)

        sync_lock.release_write()

    def _summarize_object(self, obj):
        if obj.is_tag:
            return obj.tag
        return obj.id

    def summarize_taglist(self, taglist):
        target_object = self._summarize_object(config.vars["target_object"])
        target_offset = config.vars["target_offset"]

    def test_command(self, command, test_func):
        self.gui.issue_cmd(command)
        self.gui.release_gui()
        self.wait_on_update()

        sync_lock.acquire_write()
        self.check_taglist()
        test_func()
        sync_lock.release_write()

    def test_rel_set_cursor(self):
        # This should have selected the first item

        print("Checking selection")
        if self._summarize_object(config.vars["selected"]) != "Story(2,0)":
            raise Exception("Failed to set selection!")

    def test_collapse(self):
        pass

    def test_color(self):
        self.compare_output(self.config_backend, ('SETCONFIGS', {'CantoCurses': {'color': {'8': {'bg': 0, 'fg': 0}}}}))

        if curses.pairs[8] != [ 0, 0 ]:
            raise Exception("Pair not immediately honored! %s" % curses.pairs[8])

    def check(self):
        taglist = self.get_taglist()

        while taglist.last_story == None:
            time.sleep(0.1)

        self.check_taglist()

        self.test_command("rel-set-cursor 1", self.test_rel_set_cursor)
        self.test_command("collapse", self.test_collapse)
        self.test_command("color 8 black black", self.test_color)

        self.check_taglist()

        return True

TestScreen("screen")
