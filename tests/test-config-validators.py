#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from base import *

from canto_curses.main import CANTO_PROTOCOL_COMPATIBLE
from canto_curses.config import config

import time

class TestConfigValidators(Test):
    def check(self):
        script = {
            'VERSION' : { '*' : ('VERSION', CANTO_PROTOCOL_COMPATIBLE) },
            'CONFIGS' : { '*' : ('CONFIGS', { "CantoCurses" : config.template_config }) },
                
        }

        backend = TestBackend("config", script)

        config.init(backend, CANTO_PROTOCOL_COMPATIBLE)

        # We only want to test failure. Success will be tested by the config hook test.

        really_bad_config = eval(repr(config.template_config))
        really_bad_config["browser"]["text"] = "badoption"

        backend.inject("CONFIGS", { "CantoCurses" : really_bad_config })
        
        return config.config == config.template_config

TestConfigValidators("config validators")
