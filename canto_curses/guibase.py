# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from command import CommandHandler, command_format

from canto_next.encoding import encoder

import logging

log = logging.getLogger("COMMON")

import sys
import os

class GuiBase(CommandHandler):

    def input(self, prompt):
        return self.callbacks["input"](prompt)

    def int(self, args):
        t, r = self._int(args, lambda : self.input("int: "))
        if t:
            return (True, t, r)
        return (False, None, None)

    @command_format([])
    def cmd_destroy(self, **kwargs):
        self.callbacks["die"](self)

    def _cfg_set_prompt(self, option, prompt):
        # Ensure the items are enumerated
        t = self.callbacks["get_opt"](option)
        self.callbacks["set_opt"](option, True)

        r = self.input(prompt)

        # Reset option to previous value
        self.callbacks["set_opt"](option, t)
        return r

    def _fork(self, path, href, text):
        pid = os.fork()
        if not pid :
            # A lot of programs don't appreciate
            # having their fds closed, so instead
            # we dup them to /dev/null.

            fd = os.open("/dev/null", os.O_RDWR)
            os.dup2(fd, sys.stderr.fileno())

            if not text:
                os.setpgid(os.getpid(), os.getpid())
                os.dup2(fd, sys.stdout.fileno())

            path = path.replace("%u", href)
            path = encoder(path)

            os.execv("/bin/sh", ["/bin/sh", "-c", path])

            # Just in case.
            sys.exit(0)

        return pid

    def _goto(self, urls):
        browser = self.callbacks["get_opt"]("browser")
        txt_browser = self.callbacks["get_opt"]("txt_browser")

        if not browser:
            log.error("No browser defined! Cannot goto.")
            return

        if txt_browser:
            self.callbacks["pause_interface"]()

        for url in urls:
            pid = self._fork(browser, url, txt_browser)
            if txt_browser:
                os.waitpid(pid, 0)

        if txt_browser:
            self.callbacks["unpause_interface"]()
