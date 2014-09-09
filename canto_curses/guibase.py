# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2014 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.hooks import on_hook
from canto_next.plugins import Plugin

from .command import CommandHandler, register_commands, register_arg_types, unregister_all, _string, register_aliases

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

        args = {
            "key": ("[key]:\nSimple keys (a), basic chords (C-r, M-a), or named whitespace like space or tab", _string),
            "command": ("[command]:\nAny canto-curses command. Can be chained with &, other uses of & should be quoted or escaped.", _string),
            "remote-cmd": ("[remote cmd]", self.type_remote_cmd),
            "url" : ("[URL]", _string),
        }

        cmds = {
            "bind" : (self.cmd_bind, [ "key", "command" ], "Add bind to %s" % self),
            "transform" : (self.cmd_transform, ["string"], "Set user transform"),
            "remote addfeed" : (lambda x : self.cmd_remote("addfeed", x), ["url"], "Subscribe to a feed."),
            "remote": (self.cmd_remote, ["remote-cmd", "string"], "Give a command to canto-remote"),
            "destroy": (self.cmd_destroy, [], "Destroy this window"),
        }

        aliases = {
            "browser" : "remote one-config CantoCurses.browser.path",
            "txt_browser" : "remote one-config --eval CantoCurses.browser.text",
            "add" : "remote addfeed",
            "del" : "remote delfeed",
            "list" : "remote listfeeds",
            "global_transform" : "remote one-config defaults.global_transform",
            "cursor_type" : "remote one-config CantoCurses.taglist.cursor.type",
            "cursor_scroll" : "remote one-config CantoCurses.taglist.cursor.scroll",
            "cursor_edge" : "remote one-config --eval CantoCurses.taglist.cursor.edge",
            "story_unselected" : "remote one-config CantoCurses.story.unselected",
            "story_selected" : "remote one-config CantoCurses.story.selected",
            "story_selected_end" : "remote one-config CantoCurses.story.selected_end",
            "story_unselected_end" : "remote one-config CantoCurses.story.unselected_end",
            "story_unread" : "remote one-config CantoCurses.story.unread",
            "story_read" : "remote one-config CantoCurses.story.read",
            "story_read_end" : "remote one-config CantoCurses.story.read_end",
            "story_unread_end" : "remote one-config CantoCurses.story.unread_end",
            "story_unmarked" : "remote one-config CantoCurses.story.unmarked",
            "story_marked" : "remote one-config CantoCurses.story.marked",
            "story_marked_end" : "remote one-config CantoCurses.story.marked_end",
            "story_unmarked_end" : "remote one-config CantoCurses.story.unmarked_end",
            "tag_unselected" : "remote one-config CantoCurses.tag.unselected",
            "tag_selected" : "remote one-config CantoCurses.tag.selected",
            "tag_selected_end" : "remote one-config CantoCurses.tag.selected_end",
            "tag_unselected_end" : "remote one-config CantoCurses.tag.unselected_end",
            "update_interval" : "remote one-config --eval CantoCurses.update.auto.interval",
            "update_style" : "remote one-config CantoCurses.update.style",
            "update_auto" : "remote one-config --eval CantoCurses.update.auto.enabled",
            "border" : "remote one-config --eval CantoCurses.taglist.border",
            "reader_align" : "remote one-config CantoCurses.reader.window.align",
            "reader_float" : "remote one-config --eval CantoCurses.reader.window.float",
            "keep_time" : "remote one-config --eval defaults.keep_time",
            "keep_unread" : "remote one-config --eval defaults.keep_unread",
            "kill_daemon_on_exit" : "remote one-config --eval CantoCurses.kill_daemon_on_exit",
            "filter" : "transform",
            "sort" : "transform",
        }

        register_arg_types(self, args)
        register_commands(self, cmds)
        register_aliases(self, aliases)

        self.editor = None

    def cmd_destroy(self):
        self.callbacks["die"](self)

    def die(self):
        unregister_all(self)

    def _fork(self, path, href, text, fetch=False):

        # Prepare temporary files, if fetch.

        if fetch:
            # Get a path (sans query strings, etc.) for the URL
            tmppath = urllib.parse.urlparse(href).path

            # Return just the basename of the path (no directories)
            fname = os.path.basename(tmppath)

            # Grab a temporary directory. This allows us to create a file with
            # an unperturbed filename so scripts can freely use regex /
            # extension matching in addition to mimetype detection.

            tmpdir = tempfile.mkdtemp(prefix="canto-")
            tmpnam = tmpdir + '/' + fname

            on_hook("curses_exit", lambda : (os.unlink(tmpnam)))
            on_hook("curses_exit", lambda : (os.rmdir(tmpdir)))

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

        if "%u" in path:
            path = path.replace("%u", href)
        elif href:
            path = path + " " + href

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
        f.write(text)
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

    def cmd_edit(self, **kwargs):
        t = self.callbacks["get_opt"](kwargs["opt"])
        r = self._edit(t)
        log.info("Edited %s to %s" % (kwargs["opt"], r))
        self.callbacks["set_opt"](kwargs["opt"], r)

    def type_remote_cmd(self):
        remote_cmds = [ "help", "addfeed", "listfeeds", "delfeed",
                "force-update", "config", "one-config", "export",
                "import", "kill" ]
        return (remote_cmds, lambda x : (x in remote_cmds, x))

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

    def cmd_remote(self, remote_cmd, args):
        self._remote("%s %s" % (remote_cmd, args))

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

    def cmd_transform(self, transform):
        tag_updater.transform("user", transform)
        tag_updater.update()

    def cmd_bind(self, key, cmd):
        self.bind(key, cmd, True)

    def bind(self, key, cmd, overwrite=False):
        opt = self.get_opt_name()
        key = self.translate_key(key)
        c = self.callbacks["get_conf"]()
        if not cmd:
            if key in c[opt]["key"]:
                log.info("[%s] %s = %s" % (opt, key, c[opt]["key"][key]))
                return True
            else:
                return False
        else:
            if key in c[opt]["key"] and c[opt]["key"][key] and not overwrite:
                log.debug("%s already bound to %s" % (key, c[opt]["key"][key]))
                return False

            log.debug("Binding %s.%s to %s" % (opt, key, cmd))

            c[opt]["key"][key] = cmd
            self.callbacks["set_conf"](c)
            return True
