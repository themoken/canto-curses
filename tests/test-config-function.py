#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from base import *

from canto_curses.main import CANTO_PROTOCOL_COMPATIBLE
from canto_curses.config import config

from canto_next.hooks import on_hook
from canto_next.remote import access_dict

OPT_CHANGE = 1
TAG_OPT_CHANGE = 2
DEF_OPT_CHANGE = 4
FEED_OPT_CHANGE = 8
NEW_TAG = 16
DEL_TAG = 32
EVAL_TAGS = 64

class TestConfigFunction(Test):
    def reset_flags(self):
        self.flags = 0
        self.oc_opts = None
        self.toc_opts = None
        self.doc_opts = None
        self.foc_opts = None
        self.new_tags = None
        self.del_tags = None

    def on_opt_change(self, opts):
        self.flags |= OPT_CHANGE
        self.oc_opts = opts
    
    def on_tag_opt_change(self, opts):
        self.flags |= TAG_OPT_CHANGE
        self.toc_opts = opts

    def on_def_opt_change(self, opts):
        self.flags |= DEF_OPT_CHANGE
        self.doc_opts = opts

    def on_feed_opt_change(self, opts):
        self.flags |= FEED_OPT_CHANGE
        self.foc_opts = opts

    def on_new_tag(self, tag):
        self.flags |= NEW_TAG
        self.new_tags = tag

    def on_del_tag(self, tag):
        self.flags |= DEL_TAG
        self.del_tags = tag

    def on_eval_tags_changed(self):
        self.flags |= EVAL_TAGS

    def compare_flags(self, value):
        if self.flags != value:
            raise Exception("Expected flags %d - got %d" % (value, self.flags))

    def compare_config(self, config, var, evalue):
        ok, got = access_dict(config, var)
        if not ok:
            raise Exception("Couldn't get %s?" % var)
        if got != evalue:
            raise Exception("Expected %s == %s - got %s" % (var, evalue, got))

    def compare_var(self, var, evalue):
        if hasattr(self, var):
            val = getattr(self, var)
            if val != evalue:
                raise Exception("Expected self.%s == %s - got %s" % (var, evalue, val))
        else:
            raise Exception("Couldn't get self.%s?" % var)

    def check(self):
        script = {
            'VERSION' : { '*' : ('VERSION', CANTO_PROTOCOL_COMPATIBLE) },
            'CONFIGS' : { '*' : ('CONFIGS', { "CantoCurses" : config.template_config }) },
                
        }

        backend = TestBackend("config", script)

        config.init(backend, CANTO_PROTOCOL_COMPATIBLE)

        on_hook("curses_tag_opt_change", self.on_tag_opt_change)
        on_hook("curses_opt_change", self.on_opt_change)
        on_hook("curses_def_opt_change", self.on_def_opt_change)
        on_hook("curses_feed_opt_change", self.on_feed_opt_change)
        on_hook("curses_new_tag", self.on_new_tag)
        on_hook("curses_del_tag", self.on_del_tag)
        on_hook("curses_eval_tags_changed", self.on_eval_tags_changed)

        # 1. Only Opt_change

        self.reset_flags()

        test_config = eval(repr(config.template_config))
        test_config["browser"]["path"] = "testoption"

        backend.inject("CONFIGS", { "CantoCurses" : test_config })

        self.compare_flags(OPT_CHANGE)
        self.compare_config(config.config, "browser.path", "testoption")

        # Check that the opt change hook got the smallest possible changeset

        self.compare_var("oc_opts", { "browser" : { "path" : "testoption" }})

        # 2. Invalid Tag_opt_change

        self.reset_flags()

        test_config = { "tags" : { "test" : eval(repr(config.tag_template_config)) } }

        backend.inject("CONFIGS", test_config)

        self.compare_flags(0)

        # 3. NEWTAG (also causes OPT_CHANGE because of tag order being
        # expanded) Does not cause an EVAL CHANGE because test1 doesn't get
        # match by the tags setting (i.e. tags starting with maintag:)

        self.reset_flags()

        backend.inject("NEWTAGS", [ "test1" ])

        self.compare_flags(NEW_TAG | OPT_CHANGE)
        self.compare_config(config.config, "tagorder", [ "test1" ])
        self.compare_config(config.vars, "curtags", [])
        self.compare_var("new_tags", "test1")
        self.compare_var("oc_opts", { "tagorder" : [ "test1" ] })

        # 4. NEWTAG, this time with EVAL because "maintag:Slashdot" does match tags

        self.reset_flags()

        backend.inject("NEWTAGS", [ "maintag:Slashdot" ])

        self.compare_flags(NEW_TAG | OPT_CHANGE | EVAL_TAGS)

        self.compare_config(config.config, "tagorder", [ "test1", "maintag:Slashdot" ])
        self.compare_config(config.vars, "curtags", [ "maintag:Slashdot" ])

        # 5. switch_tags (promote demote)

        self.reset_flags()

        # These are fodder
        backend.inject("NEWTAGS", [ "maintag:Test2" ])
        backend.inject("NEWTAGS", [ "maintag:Test3" ])
        backend.inject("NEWTAGS", [ "maintag:Test4" ])

        self.compare_flags(NEW_TAG | OPT_CHANGE | EVAL_TAGS)
        self.compare_config(config.config, "tagorder", [ "test1", "maintag:Slashdot", "maintag:Test2","maintag:Test3", "maintag:Test4" ])
        self.compare_config(config.vars, "curtags", [ "maintag:Slashdot", "maintag:Test2", "maintag:Test3", "maintag:Test4" ])

        self.reset_flags()

        config.switch_tags("maintag:Test2", "maintag:Test3")

        self.compare_flags(OPT_CHANGE | EVAL_TAGS)
        self.compare_config(config.config, "tagorder", [ "test1", "maintag:Slashdot", "maintag:Test3","maintag:Test2", "maintag:Test4" ])
        self.compare_config(config.vars, "curtags", [ "maintag:Slashdot", "maintag:Test3", "maintag:Test2", "maintag:Test4" ])
        self.compare_var("oc_opts", { "tagorder" :  [ "test1", "maintag:Slashdot", "maintag:Test3","maintag:Test2", "maintag:Test4" ] })

        # 6. DELTAG

        self.reset_flags()

        backend.inject("DELTAGS", [ "maintag:Test4" ])

        self.compare_flags(DEL_TAG | OPT_CHANGE | EVAL_TAGS)
        self.compare_config(config.config, "tagorder", [ "test1", "maintag:Slashdot", "maintag:Test3","maintag:Test2"])
        self.compare_config(config.vars, "curtags", [ "maintag:Slashdot", "maintag:Test3", "maintag:Test2"])
        self.compare_var("del_tags", "maintag:Test4")

        # 7. Changing the tags regex

        self.reset_flags()

        # More fodder
        backend.inject("NEWTAGS", [ "alt:t1" ])
        backend.inject("NEWTAGS", [ "alt:t2" ])
        backend.inject("NEWTAGS", [ "alt:t3" ])

        self.compare_flags(NEW_TAG | OPT_CHANGE)
        self.compare_config(config.config, "tagorder", [ "test1", "maintag:Slashdot", "maintag:Test3","maintag:Test2", "alt:t1", "alt:t2", "alt:t3" ])
        self.compare_config(config.vars, "curtags", [ "maintag:Slashdot", "maintag:Test3", "maintag:Test2"])
        self.reset_flags()

        c = config.get_conf()
        c["tags"] = "alt:.*"
        config.set_conf(c)

        self.compare_flags(OPT_CHANGE | EVAL_TAGS)
        return True

TestConfigFunction("config function")
