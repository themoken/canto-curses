#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from canto_curses.main import CANTO_PROTOCOL_COMPATIBLE
from canto_curses.config import config

import time

# Like main.py, except instead of communicating with a real server, it reads
# from a script.

class TestBackend(object):
    def __init__(self, prefix, script):
        self.prefix = prefix
        self.location_args = ""
        self.responses = []

        self.script = script

    def connect(self):
        return 0

    def do_write(self, conn, cmd, args):
        print("%s write %s - %s" % (self.prefix, cmd, args))
        
        found_response = False
        r = None

        for key in self.script.keys():
            if key == cmd:
                responses = self.script[key]
                if repr(args) in responses:
                    found_response = True
                    r = responses[args]
                    break
                elif "*" in responses:
                    found_response = True
                    r = responses["*"]
                    break
        if not found_response:
            return

        print(" -> queued response %s" % (r,))

        self.responses.append(r)

    def do_read(self, conn):
        while self.responses == []:
            time.sleep(0.1)
        r = self.responses[0]
        self.responses = self.responses[1:]
        print("%s read %s" % (self.prefix, r))
        return r

    def inject(self, cmd, args):
        self.responses.append({ cmd : args })

class Test(object):
    def __init__(self, name):
        self.name = name
        self.run()
    
    def run(self):
        print("STARTING %s\n" % self.name)
        r = self.check()
        if r == True:
            print("\n%s - PASSED\n" % self.name)
            return 0

        print("\n%s - FAILED\n" % self.name)
        return 1

    def check(self):
        pass

class VersionCheckTest(Test):
    def __init__(self):
        Test.__init__(self, "version check")

    def check(self):
        version_check_script = { 'VERSION' : { '*' : ('VERSION', 0.1) } }

        backend = TestBackend("config", version_check_script)

        return config.init(backend, CANTO_PROTOCOL_COMPATIBLE) == False

VersionCheckTest()

# Like gui.py

callbacks = {
    "set_var" : config.set_var,
    "get_var" : config.get_var,
    "set_conf" : config.set_conf,
    "get_conf" : config.get_conf,
    "set_tag_conf" : config.set_tag_conf,
    "get_tag_conf" : config.get_tag_conf,
    "set_defaults" : config.set_def_conf,
    "get_defaults" : config.get_def_conf,
    "set_feed_conf" : config.set_feed_conf,
    "get_feed_conf" : config.get_feed_conf,
    "get_opt" : config.get_opt,
    "set_opt" : config.set_opt,
    "get_tag_opt" : config.get_tag_opt,
    "set_tag_opt" : config.set_tag_opt,
}
