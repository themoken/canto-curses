# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2016 Jack Miller <jack@codezen.org>
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
        self.style_conf = config.get_opt("style")
        on_hook("curses_opt_change", self.on_opt_change, self)

    def on_opt_change(self, config):
        if "color" in config:
            self.color_conf = config["color"]
        if "style" in config:
            self.style_conf = config["style"]

    def _invert(self, codes):
        inverted = ""

        in_code = False
        long_code = False

        for c in codes:
            if in_code:
                if long_code:
                    if c == "]":
                        inverted += "%0"
                        long_code = False
                else:
                    if c in "12345678":
                        inverted += "%0"
                    elif c in "BRDSU":
                        inverted += "%" + c.lower()
                    elif c == "[":
                        long_code = True
                    in_code = False
            elif c == "%":
                in_code = True
        return inverted

    def __call__(self, name):
        color = ""

        if self.color_conf[name] > 8:
            color = "%[" + str(self.color_conf[name]) + "]"
        elif self.color_conf[name] > 0:
            color = "%" + str(self.color_conf[name])

        return color + self.style_conf[name]

    def end(self, name):
        return self._invert(self(name))

cc = CantoColorManager()
