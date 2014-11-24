# -*- coding: utf-8 -*-

def waddch(pad, ch):
    pad.waddch(ch)

import sys

self = sys.modules[__name__]
real_widecurse = __import__("canto_curses.widecurse")

for attr in dir(real_widecurse.widecurse):
    print("ATTR: %s" % attr)
    if not hasattr(self, attr):
        print("SUBBING: %s" % attr)
        setattr(self, attr, getattr(real_widecurse.widecurse, attr))
