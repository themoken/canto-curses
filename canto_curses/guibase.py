# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.hooks import call_hook, on_hook
from canto_next.encoding import encoder
from canto_next.plugins import Plugin

from .command import CommandHandler, command_format

import logging

log = logging.getLogger("COMMON")

import subprocess
import tempfile
import urllib.request, urllib.error, urllib.parse
import shlex
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

    def _fork(self, path, href, text, fetch=False):

        # Prepare temporary files, if fetch.

        if fetch:
            # Get a path (sans query strings, etc.) for the URL
            tmppath = urllib2.urlparse.urlparse(href).path

            # Return just the basename of the path (no directories)
            fname = os.path.basename(tmppath)

            # Grab a temporary directory. This allows us to create a file with
            # an unperturbed filename so scripts can freely use regex /
            # extension matching in addition to mimetype detection.

            tmpdir = tempfile.mkdtemp(prefix="canto-")
            tmpnam = tmpdir + '/' + fname

            on_hook("exit", lambda : (os.unlink(tmpnam)))
            on_hook("exit", lambda : (os.rmdir(tmpdir)))

        pid = os.fork()

        # Parents can now bail.
        if pid:
            return pid

        if fetch:
            tmp = open(tmpnam, 'w+b')

            # Grab the HTTP info / prepare to read.
            response = urllib.request.urlopen(href)

            # Grab in kilobyte chunks to avoid wasting memory on something
            # that's going to be immediately written to disk.

            while True:
                r = response.read(1024)
                if not r:
                    break
                tmp.write(r)

            response.close()
            tmp.close()

            href = tmpnam

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
        f.write(encoder(text))
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

    # Pass-thru for arbitrary, unquoted strings.
    def string(self, args, prompt):
        if not args:
            args = prompt()
        return (True, args, None)

    # Parse a string in shell fashion, returning components.

    def split_string(self, args, prompt):
        if not args:
            args = prompt()

        return (True, shlex.split(args), None)

    def one_opt(self, args):
        t, r = self._first_term(args,
                lambda : self.input("opt: "))
        if not t:
            return (False, None, None)
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

    def _remote_argv(self, argv):
        loc_args = self.callbacks["get_var"]("location")
        argv = [argv[0]] + loc_args + argv[1:]

        log.debug("Calling remote: %s" % argv)

        # check_output return bytes, we must decode.
        out = subprocess.check_output(argv).decode()

        log.debug("Output:")
        log.debug(out)

        # Strip anything that could be misconstrued as style
        # from remote output.

        out = out.replace("%","\\%")

        log.info(out)

    def _remote(self, args):
        args = "canto-remote " + args

        # Add location args, so the remote is connecting
        # to the correct daemon.

        self._remote_argv(shlex.split(args))

    def remote_args(self, args):
        return self.string(args, "remote: ")

    @command_format([("remote_args","remote_args")])
    def cmd_remote(self, **kwargs):
        self._remote(kwargs["remote_args"])

    def _goto(self, urls, fetch=False):
        browser = self.callbacks["get_conf"]()["browser"]

        if not browser["path"]:
            log.error("No browser defined! Cannot goto.")
            return

        if browser["text"]:
            self.callbacks["pause_interface"]()

        for url in urls:
            pid = self._fork(browser["path"], url, browser["text"], fetch)
            if browser["text"]:
                os.waitpid(pid, 0)

        if browser["text"]:
            self.callbacks["unpause_interface"]()

    # Like goto, except download the file to /tmp before executing browser.

    def _fetch(self, urls):
        self._goto(urls, True)

    def named_key(self, args):
        return self.input_key(args, lambda : self.callbacks["input"]("key: "))
