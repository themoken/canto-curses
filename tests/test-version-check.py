#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from base import *

from canto_curses.main import CANTO_PROTOCOL_COMPATIBLE
from canto_curses.config import config

class VersionCheckTest(Test):
    def check(self):
        version_check_script = { 'VERSION' : { '*' : ('VERSION', 0.1) } }

        backend = TestBackend("config", version_check_script)

        return config.init(backend, CANTO_PROTOCOL_COMPATIBLE) == False

VersionCheckTest("version check")
