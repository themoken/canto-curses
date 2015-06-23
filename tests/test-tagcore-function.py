#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from base import *

from canto_curses.main import CANTO_PROTOCOL_COMPATIBLE
from canto_curses.config import config
from canto_curses.tagcore import tag_updater, alltagcores

from canto_next.hooks import on_hook, call_hook

ITEMS_REMOVED = 1
ITEMS_ADDED = 2
NEW_TC = 4
DEL_TC = 8
ATTRIBUTES = 16
UPDATE_COMPLETE = 32

class FakeTag(object):
    def __init__(self, tag):
        self.tag = tag

class FakeStory(object):
    def __init__(self, id):
        self.id = id

class TestTagCoreFunction(Test):

    def reset_flags(self):
        self.flags = 0
        self.oir_tctag = None
        self.oir_tcids = None
        self.oia_tctag = None
        self.oia_tcids = None
        self.new_tc = None
        self.del_tc = None
        self.attributes = None

    def on_items_removed(self, tagcore, removed):
        self.flags |= ITEMS_REMOVED
        self.oir_tctag = tagcore.tag
        self.oir_tcids = removed

    def on_items_added(self, tagcore, added):
        self.flags |= ITEMS_ADDED
        self.oia_tctag = tagcore.tag
        self.oia_tcids = added

    def on_new_tagcore(self, tagcore):
        self.flags |= NEW_TC
        self.new_tc = tagcore.tag

    def on_del_tagcore(self, tagcore):
        self.flags |= DEL_TC
        self.del_tc = tagcore.tag

    def on_attributes(self, attributes):
        self.flags |= ATTRIBUTES
        self.attributes = attributes

    def on_update_complete(self):
        self.flags |= UPDATE_COMPLETE

    def check(self):
        config_script = {
            'VERSION' : { '*' : [('VERSION', CANTO_PROTOCOL_COMPATIBLE)] },
            'CONFIGS' : { '*' : [('CONFIGS', { "CantoCurses" : config.template_config })] },
                
        }

        config_backend = TestBackend("config", config_script)

        config.init(config_backend, CANTO_PROTOCOL_COMPATIBLE)

        config_backend.inject("NEWTAGS", [ "maintag:Slashdot", "maintag:reddit" ])

        tagcore_script = {}

        tag_backend = TestBackend("tagcore", tagcore_script)

        on_hook("curses_items_removed", self.on_items_removed)
        on_hook("curses_items_added", self.on_items_added)
        on_hook("curses_new_tagcore", self.on_new_tagcore)
        on_hook("curses_del_tagcore", self.on_del_tagcore)
        on_hook("curses_attributes", self.on_attributes)
        on_hook("curses_update_complete", self.on_update_complete)

        # 1. Previously existing tags in config should be populated on init

        self.reset_flags()

        tag_updater.init(tag_backend)

        for tag in config.vars["strtags"]:
            for tc in alltagcores:
                if tc.tag == tag:
                    break
            else:
                raise Exception("Couldn't find TC for tag %s" % tag)

        self.compare_flags(NEW_TC)

        self.reset_flags()

        # 2. Getting empty ITEMS responses should cause no events

        tag_backend.inject("ITEMS", { "maintag:Slashdot" : [] })
        tag_backend.inject("ITEMSDONE", {})

        tag_backend.inject("ITEMS", { "maintag:reddit" : [] })
        tag_backend.inject("ITEMSDONE", {})

        self.compare_flags(0)

        # 3. Getting a non-empty ITEMS response should cause items_added

        tag_backend.inject("ITEMS", { "maintag:Slashdot" : [ "id1", "id2" ] })
        tag_backend.inject("ITEMSDONE", {})

        self.compare_flags(ITEMS_ADDED)

        # 4. Getting attributes should cause attributes hook

        self.reset_flags()

        id1_content = { "title" : "id1", "canto-state" : [], "canto-tags" : [],
                "link" : "id1-link", "enclosures" : "" }

        id2_content = { "title" : "id2", "canto-state" : [], "canto-tags" : [],
                "link" : "id2-link", "enclosures" : "" }

        all_content = { "id1" : id1_content, "id2" : id2_content }

        tag_backend.inject("ATTRIBUTES", all_content)

        self.compare_flags(ATTRIBUTES)
        self.compare_var("attributes", all_content)

        id1_got = tag_updater.get_attributes("id1")
        if id1_got != id1_content:
            raise Exception("Bad content: wanted %s - got %s" % (id1_content, id1_got))
        id2_got = tag_updater.get_attributes("id2")
        if id2_got != id2_content:
            raise Exception("Bad content: wanted %s - got %s" % (id2_content, id2_got))

        # 5. Removing an item should *NOT* cause its attributes to be forgotten
        # that happens on stories_removed, and should cause ITEMS_REMOVED

        self.reset_flags()

        tag_backend.inject("ITEMS", { "maintag:Slashdot" : [ "id1" ] })
        tag_backend.inject("ITEMSDONE", {})

        self.compare_flags(ITEMS_REMOVED)

        id2_got = tag_updater.get_attributes("id2")
        if id2_got != id2_content:
            raise Exception("Bad content: wanted %s - got %s" % (id2_content, id2_got))

        # 6. Getting a stories_removed hook should make it forget attributes

        self.reset_flags()
        
        call_hook("curses_stories_removed", [ FakeTag("maintag:Slashdot"), [ FakeStory("id2") ] ])
                
        if "id2" in tag_updater.attributes:
            raise Exception("Expected id2 to be removed, but it isn't!")

        self.compare_flags(0)

        # 7. Getting attributes for non-existent IDs should return empty

        id2_got = tag_updater.get_attributes("id2")
        if id2_got != {}:
            raise Exception("Expected non-existent id to return empty! Got %s" % id2_got)

        self.compare_flags(0)

        # 8. Getting stories_removed for item still in tag should do nothing

        call_hook("curses_stories_removed", [ FakeTag("maintag:Slashdot"), [ FakeStory("id1") ] ])

        if "id1" not in tag_updater.attributes:
            raise Exception("Expected id1 to remain in attributes!")

        self.compare_flags(0)

        # 9. Config adding a tag should create a new tagcore

        config_backend.inject("NEWTAGS", [ "maintag:Test1" ])

        self.compare_flags(NEW_TC)

        # 10. Config removing an empty tag should delete a tagcore

        self.reset_flags()

        config_backend.inject("DELTAGS", [ "maintag:reddit" ])

        self.compare_flags(DEL_TC)
        self.compare_var("del_tc", "maintag:reddit")

        # 11. Config removing an populated tag should delete a tagcore and
        # cause items_removed. NOTE for now tagcores are never deleted, they
        # just exist empty

        self.reset_flags()

        config_backend.inject("DELTAGS", [ "maintag:Slashdot" ])

        self.compare_flags(DEL_TC | ITEMS_REMOVED)
        self.compare_var("del_tc", "maintag:Slashdot")
        self.compare_var("oir_tctag", "maintag:Slashdot")
        self.compare_var("oir_tcids", [ "id1" ])

        # 12. Reset should empty all tagcores and ignore all traffic
        # until it receives a PONG for every reset() PING

        self.reset_flags()

        tag_updater.reset()

        for tc in alltagcores:
            if len(tc) > 0:
                raise Exception("TC %s not empty!" % tc.tag)

        tag_backend.inject("ITEMS", { "maintag:Test1" : [ "id3", "id4" ] })
        tag_backend.inject("ITEMSDONE", {})
        tag_backend.inject("ATTRIBUTES", { "id3" : { "test" : "test" }, "id4" : { "test" : "test" }})

        self.compare_flags(0)
        if "id3" in tag_updater.attributes:
            raise Exception("Shouldn't have gotten id3!")
        if "id4" in tag_updater.attributes:
            raise Exception("Shouldn't have gotten id4!")

        tag_updater.reset()
        
        tag_backend.inject("PONG", {})

        tag_backend.inject("ITEMS", { "maintag:Test1" : [ "id3", "id4" ] })
        tag_backend.inject("ITEMSDONE", {})
        tag_backend.inject("ATTRIBUTES", { "id3" : { "test" : "test" }, "id4" : { "test" : "test" }})

        self.compare_flags(0)
        if "id3" in tag_updater.attributes:
            raise Exception("Shouldn't have gotten id3!")
        if "id4" in tag_updater.attributes:
            raise Exception("Shouldn't have gotten id4!")

        tag_backend.inject("PONG", {})
        tag_backend.inject("ITEMS", { "maintag:Test1" : [ "id3", "id4" ] })
        tag_backend.inject("ITEMSDONE", {})
        tag_backend.inject("ATTRIBUTES", { "id3" : { "test" : "test" }, "id4" : { "test" : "test" }})

        self.compare_flags(ITEMS_ADDED | ATTRIBUTES)

        if "id3" not in tag_updater.attributes:
            raise Exception("Should have gotten id3!")
        if "id4" not in tag_updater.attributes:
            raise Exception("Should have gotten id4!")

        # 13. Non-force reset not allowed during update

        tag_updater.update()

        if tag_updater.reset() != False:
            raise Exception("Should have rejected reset()")

        # 14. Update complete should trigger on receiving items from update
        # and a subsequent reset() should work

        self.reset_flags()
        tag_backend.inject("ITEMS", { "maintag:Test1" : [ "id3", "id4" ] })
        tag_backend.inject("ITEMSDONE", {})

        self.compare_flags(UPDATE_COMPLETE)

        if tag_updater.reset() != True:
            raise Exception("Shouldn't have rejected reset()!")

        tag_backend.inject("PONG", {})

        return True

TestTagCoreFunction("tagcore function")
