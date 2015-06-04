# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2014 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.hooks import on_hook

from .config import config

# color code, convert a symbolic color name (e.g. "unread") into a code to put
# in a theme string

class CantoColorManager:
    def __init__(self):
        self.color_conf = config.get_opt("color")
        on_hook("curses_opt_change", self.on_opt_change, self)

    def on_opt_change(self, config):
        if "color" in config:
            self.color_conf = config["color"]

    def __call__(self, name):
        return "%" + str(self.color_conf[name])

cc = CantoColorManager()
