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
from canto_curses.gui import CantoCursesGui, GraphicalLog # to Screen to curses
from canto_curses.locks import sync_lock
from canto_curses.taglist import TagList
from canto_curses.tag import alltags

from canto_next.hooks import on_hook, call_hook

import time

class TestScreen(Test):
    def __init__(self, name):
        config_script = {
            'VERSION' : { '*' : [('VERSION', CANTO_PROTOCOL_COMPATIBLE)] },
            'CONFIGS' : { '*' : [('CONFIGS', { "CantoCurses" : config.template_config })] },
            'PING' : { '*' : [("PONG", [])]}
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

        gui_script = {}

        self.gui_backend = TestBackend("gui", gui_script)

        self.glog = GraphicalLog()
        self.gui = CantoCursesGui(self.gui_backend, self.glog)
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

        self.wait_on_update()

        Test.__init__(self, name)

    def wait_on_update(self):
        while True:
            ref = config.vars["needs_refresh"]
            red = config.vars["needs_redraw"]
            res = config.vars["needs_resize"]
            wrk = self.gui.working
            sr = self.gui.sync_requested
            print("ref red res wrk sr - %s %s %s %s %s" % (ref, red, res, wrk, sr))
            if not (ref or red or res or wrk or sr):
                return
            time.sleep(0.1)

    def compare_output(self, backend, evalue):
        if backend.output[-1] != evalue:
            raise Exception("Unexpected output - %s\n\nWanted %s" % (backend.output[-1], evalue))

    # This is all about making sure that all of the items that are referenced
    # in this list belong there, and are properly setup.

    def check_taglist_obj(self, taglist, target_object, recurse_attr=""):
        if not target_object:
            return

        summary = self._summarize_object(target_object)

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

    # Generate an easy to read summary of the taglist, following a certain
    # attribute from a certain object so that large chains of items can be
    # easily referenced by index instead of the linked list version that the
    # taglist actually uses. Always starts with target_object / target_offset
    # as these are integral to proper rendering.

    def summarize_taglist(self, starting_object, follow_attr):
        target_object = self._summarize_object(config.vars["target_obj"])
        target_offset = config.vars["target_offset"]

        rest = []
        while starting_object:
            # Record current position, or -1 if off screen.
            pos = -1
            if hasattr(starting_object, "curpos"):
                pos = starting_object.curpos

            rest.append((self._summarize_object(starting_object), pos))

            if not hasattr(starting_object, follow_attr):
                raise Exception("Couldn't find follow_attr %s" % follow_attr)
            starting_object = getattr(starting_object, follow_attr)

        return [(target_object, target_offset)] + rest

    def test_command(self, command, test_func, no_check=False):
        print("Issuing %s" % command)
        self.gui.issue_cmd(command)
        self.gui.release_gui()
        self.wait_on_update()

        sync_lock.acquire_write()
        if not no_check:
            self.check_taglist()
        if test_func:
            test_func()
        sync_lock.release_write()

    def test_rel_set_cursor(self):
        # This should have selected the first item

        print("Checking selection")
        summ = self._summarize_object(config.vars["selected"])
        if summ != "Story(0,0)":
            raise Exception("Failed to set selection! Is %s" % summ)

    # Test :collapse by seeing if the summary of next_sel properly skips from
    # the first tag (affected by the :collapse call) to the next tag without
    # any of the intervening stories.

    def test_collapse(self):
        taglist = self.get_taglist()
        summ = self.summarize_taglist(taglist.first_sel, "next_sel")

        # Target should be tag @ 0, as should the first sel
        if summ[0] != ("maintag:Tag(0)", 0):
            raise Exception("Failed to properly set target on :collapse")
        if summ[1] != ("maintag:Tag(0)", 0):
            raise Exception("Failed to properly set first_sel on :collapse")

        # The selection after that should be the first story of the next
        # (uncollapsed) tag.

        # XXX: This will fail if we decide to change widths such that the tag
        # header takes more than one line.

        # XXX: Also hold off on this until we can guarantee order without +/-

        #if summ[2] != ("Story(1,0)", 2):
        #    raise Exception("Failed to properly set first_sel on :collapse: %s" % (summ[2],))

    def test_uncollapse(self):
        taglist = self.get_taglist()
        summ = self.summarize_taglist(taglist.first_sel, "next_sel")

        # Should be story since we went from first sel.
        # NOTE: This 1 is width sensitive.

        if summ[0] != ("Story(0,0)", 1):
            raise Exception("Failed to properly set target on :uncollapse")
        if summ[1] != ("Story(0,0)", 1):
            raise Exception("Failed to properly set first_sel on :uncollapse")

    def test_sel_disappear(self):
        tagcore_script = generate_item_script(2, 20, "maintag:Tag(%d)", "Story(%d,%d)",
                { "title" : "%d,%d - title", "link" : "http://example.com/%d/%d",
                    "description" : "Description(%d,%d)", "canto-tags" : "",
                    "canto-state" : "" }
        )

        # Stub in an empty tag

        tagcore_script["ITEMS"]["['maintag:Tag(0)']"] = [("ITEMS", {'maintag:Tag(0)': [] }), ("ITEMSDONE", {}) ]

        self.tag_backend.script = tagcore_script
        self.tag_backend.inject("TAGCHANGE", "maintag:Tag(0)")

        taglist = self.get_taglist()
        summ = self.summarize_taglist(taglist.first_sel, "next_sel")

        # With just the items removed from the TagCores, selection and friends
        # shouldn't have changed at all.

        if summ[0] != ("Story(0,0)", 1):
            raise Exception("target_obj changed on ITEMS")
        if summ[1] != ("Story(0,0)", 1):
            raise Exception("sel changed on ITEMS")
        if summ[2] != ("Story(0,1)", 2):
            raise Exception("Improper follow up!")

        # XXX: This is a hack, but we need to yield long enough for the tagcore
        # thread to actually process the ITEMS response from TAGCHANGE

        time.sleep(1)

        # After an update, it should actually change. Add no_check, so that we
        # don't throw an exception when we discover that the selection is no
        # longer in TagCore.

        self.test_command("update", self.post_update_sel_should_not_disappear, True)

        self.test_command("next-item", None, True)

        self.test_command("update", self.post_update_oldsel_should_be_gone, True)

    def post_update_sel_should_not_disappear(self):
        taglist = self.get_taglist()
        summ = self.summarize_taglist(taglist.first_sel, "next_sel")

        # Now sel should still be there, but should be the only one in the tag.

        if summ[0] != ("Story(0,0)", 1):
            raise Exception("target_obj changed on ITEMS")
        if summ[1] != ("Story(0,0)", 1):
            raise Exception("sel changed on ITEMS")
        if summ[2] == ("Story(0,1)", 2):
            raise Exception("Improper follow up!")

    def post_update_oldsel_should_be_gone(self):
        taglist = self.get_taglist()
        summ = self.summarize_taglist(taglist.first_sel, "next_sel")

        for tag in alltags:
            print("%s" % tag.tag)
            for story in tag:
                print("%s" % story)

        if summ[0] == ("Story(0,0)", 1):
            raise Exception("Failed to be rid of dead selection (target)")
        if summ[1] == ("Story(0,0)", 1):
            raise Exception("Failed to be rid of dead selection (first_sel)")

    def test_color(self):
        if curses.pairs[8] != [ 0, 0 ]:
            raise Exception("Pair not immediately honored! %s" % curses.pairs[8])

    def test_del(self):
        self.config_backend.inject("DELTAGS", [ "maintag:Tag(1)" ])
        time.sleep(1)
        self.check_taglist()

    def check(self):
        taglist = self.get_taglist()

        while taglist.last_story == None:
            time.sleep(0.1)

        self.check_taglist()

        self.test_command("rel-set-cursor 1", self.test_rel_set_cursor)
        self.test_command("collapse", self.test_collapse)
        self.test_command("uncollapse", self.test_uncollapse)
        self.test_command("color 8 black black", self.test_color)

        self.test_sel_disappear()

        self.test_command("next-item", None, True)

        # Can't test this with a command because :del requires a live remote -> daemon.
        self.test_del()

        self.check_taglist()

        return True

TestScreen("screen")
