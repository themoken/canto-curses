# Xterm title set on selection change
# by Jack Miller
# v1.0

# Set to True if you want the selection title included.
USE_TITLE=False

from canto_next.hooks import on_hook

import locale
import os

prefcode = locale.getpreferredencoding()

def set_xterm_title(s):
    os.write(1, ("\033]0; %s \007" % s).encode(prefcode))

def clear_xterm_title():
    os.write(1, "\033]0; \007".encode(prefcode))

def xt_on_var_change(var_dict):
    if "selected" in var_dict:
        if var_dict["selected"] == None:
            set_xterm_title("Canto")
        else:
            set_xterm_title("Canto - " + var_dict["selected"].content["title"])

if USE_TITLE:
    on_hook("curses_var_change", xt_on_var_change)
else:
    set_xterm_title("Canto")

on_hook("curses_exit", clear_xterm_title)
