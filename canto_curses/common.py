# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from command import CommandHandler, command_format, generic_parse_error
from utility import silentfork

class GuiBase(CommandHandler):

    def input(self, prompt):
        return self.callbacks["input"](prompt)

    def int(self, args):
        t, r = self._int(args, lambda : self.input("int: "))
        if t:
            return (True, t, r)
        return (False, None, None)

    @command_format("destroy", [])
    @generic_parse_error
    def destroy(self, **kwargs):
        self.callbacks["die"](self)

    def command(self, cmd):
        if cmd.startswith("destroy"):
            self.destroy(args=cmd)

    def _cfg_set_prompt(self, option, prompt):
        # Ensure the items are enumerated
        t = self.callbacks["get_opt"](option)
        self.callbacks["set_opt"](option, True)

        r = self.input(prompt)

        # Reset option to previous value
        self.callbacks["set_opt"](option, t)
        return r

    def _goto(self, urls):
        browser = self.callbacks["get_opt"]("browser")
        txt_browser = self.callbacks["get_opt"]("txt_browser")

        if not browser:
            log.error("No browser defined! Cannot goto.")
            return

        if txt_browser:
            self.callbacks["pause_interface"]()

        for url in urls:
            pid = silentfork(browser, url)
            if txt_browser:
                os.waitpid(pid, 0)

        if txt_browser:
            self.callbacks["unpause_interface"]()
