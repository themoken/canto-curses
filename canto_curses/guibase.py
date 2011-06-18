# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from command import CommandHandler, command_format
from canto_next.encoding import encoder, locale_enc
from canto_next.plugins import Plugin
import logging

log = logging.getLogger("COMMON")

import tempfile
import sys
import os

class BasePlugin(Plugin):
    pass

class GuiBase(CommandHandler):
    def __init__(self):
        CommandHandler.__init__(self)

        self.plugin_class = BasePlugin
        self.update_plugin_lookups()

        self.editor = None

    def input(self, prompt):
        return self.callbacks["input"](prompt)

    def int(self, args):
        t, r = self._int(args, None, None, lambda : self.input("int: "))
        if t:
            return (True, t, r)
        return (False, None, None)

    @command_format([])
    def cmd_destroy(self, **kwargs):
        self.callbacks["die"](self)

    def die(self):
        pass

    def _cfg_set_prompt(self, option, prompt):
        t = self.callbacks["get_opt"](option)
        self.callbacks["set_opt"](option, True)

        # It's assumed that if we're wrapping a prompt in this
        # change, that we want to update the pad.

        if not t:
            self.redraw()

        r = self.input(prompt)

        self.callbacks["set_opt"](option, t)
        return r

    def _tag_cfg_set_prompt(self, tag, option, prompt):
        t = self.callbacks["get_tag_opt"](tag, option)
        self.callbacks["set_tag_opt"](tag, option, True)

        # Same as above, if we're wrapping a prompt, we want
        # to update the screen.

        if not t:
            self.redraw()

        r = self.input(prompt)

        self.callbacks["set_tag_opt"](tag, option, t)
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

    def _edit(self, text):
        if not self.editor:
            self.editor = os.getenv("EDITOR")
        if not self.editor:
            self.editor = self.input("editor: ")

        # No editor, or cancelled dialog, no change.
        if not self.editor:
            return text

        self.callbacks["pause_interface"]()

        # Setup tempfile to edit.
        fd, path = tempfile.mkstemp(text=True)

        f = os.fdopen(fd, "w")
        f.write(text.encode(locale_enc, "ignore"))
        f.close()

        # Invoke editor
        logging.info("Invoking editor on %s" % path)
        pid = self._fork(self.editor + " %u", path, True)
        pid, status = os.waitpid(pid, 0)

        if status == 0:
            f = open(path, "r")
            r = f.read()
            f.close()
        else:
            self.callbacks["set_var"]("error_msg",
                    "Editor failed! Status = %d" % (status,))
            r = text

        # Cleanup temp file.
        os.unlink(path)

        self.callbacks["unpause_interface"]()

        return r

    # Pass-thru for arbitrary strings.
    def string(self, args, prompt):
        if not args:
            args = prompt()
        return (True, args, None)

    def one_opt(self, args):
        t, r = self._first_term(args,
                lambda : self.input("opt: "))

        try:
            self.callbacks["get_opt"](t)
        except:
            log.error("Unknown option: %s" % t)
            return (False, None, None)
        return (True, t, None)

    @command_format([("opt", "one_opt")])
    def cmd_edit(self, **kwargs):
        t = self.callbacks["get_opt"](kwargs["opt"])
        r = self._edit(t)
        log.info("Edited %s to %s" % (kwargs["opt"], r))
        self.callbacks["set_opt"](kwargs["opt"], r)

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
