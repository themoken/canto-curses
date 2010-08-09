# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.encoding import encoder

import sys
import os

def silentfork(path, href):

    href = encoder(href)

    pid = os.fork()
    if not pid :
        # A lot of programs don't appreciate
        # having their fds closed, so instead
        # we dup them to /dev/null.

        fd = os.open("/dev/null", os.O_RDWR)
        os.dup2(fd, sys.stderr.fileno())

        path = path.replace("%u", href)

        os.execv("/bin/sh", ["/bin/sh", "-c", path])

        # Just in case.
        sys.exit(0)
