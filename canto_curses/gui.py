#!/usr/bin/python
# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

import time

class CantoCursesGui():
    def __init__(self, responses):
        self.responses = responses

    def run(self):
        time.sleep(0.01)
