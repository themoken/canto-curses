# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

COMPATIBLE_VERSION = 0.4

from canto_next.hooks import call_hook
from canto_next.plugins import Plugin
from canto_next.format import escsplit

from .tag import Tag
from .tagcore import alltagcores

from .config import config
from .command import CommandHandler, command_format
from .text import ErrorBox, InfoBox
from .screen import Screen, color_translate

from queue import Queue, Empty
import logging
import curses
import pprint
import sys
import re

log = logging.getLogger("GUI")
pp = pprint.PrettyPrinter(indent=4)

class GraphicalLog(logging.Handler):
    def __init__(self, callbacks, screen):
        logging.Handler.__init__(self)
        self.callbacks = callbacks
        self.screen = screen

    def _emit(self, var, window_type, record):
        if window_type not in self.screen.window_types:
            self.callbacks["set_var"](var, record.message)
            self.screen.add_window_callback(window_type)
        else:
            cur = self.callbacks["get_var"](var)
            cur += "\n" + record.message
            self.callbacks["set_var"](var, cur)
        self.callbacks["set_var"]("needs_refresh", True)

    def emit(self, record):
        if record.levelno == logging.INFO:
            self._emit("info_msg", InfoBox, record)
        elif record.levelno == logging.ERROR:
            self._emit("error_msg", ErrorBox, record)

class GuiPlugin(Plugin):
    pass

CONN_NEED_NOTIFY = 1
CONN_NOTIFIED = 2

class CantoCursesGui(CommandHandler):
    def __init__(self, backend):
        CommandHandler.__init__(self)

        self.plugin_class = GuiPlugin
        self.update_plugin_lookups()

        self.backend = backend
        self.screen = None

        self.update_interval = 0

        # Lines to be emitted after a graphical log is setup.
        self.early_errors = []
        self.glog_handler = None

        self.disconnect_message =\
""" Disconnected!

Please use :reconnect if the daemon is still running.

Until reconnected, it will be impossible to fetch any information, and any state changes will be lost."""

        self.reconnect_message =\
""" Successfully Reconnected!"""

        # Asynchronous notification flags
        self.disconn = 0
        self.reconn = 0
        self.ticked = False
        self.winched = False

        self.callbacks = {
            "set_var" : config.set_var,
            "get_var" : config.get_var,
            "set_conf" : config.set_conf,
            "get_conf" : config.get_conf,
            "set_tag_conf" : config.set_tag_conf,
            "get_tag_conf" : config.get_tag_conf,
            "get_opt" : config.get_opt,
            "set_opt" : config.set_opt,
            "get_tag_opt" : config.get_tag_opt,
            "set_tag_opt" : config.set_tag_opt,
            "switch_tags" : self.switch_tags,
            "write" : self.write,
        }

        # Instantiate graphical Tag objects

        for tagcore in alltagcores:
            log.debug("Instantiating Tag() for %s" % tagcore.tag)
            Tag(tagcore, self.callbacks)

        log.debug("Starting curses.")

        self.screen = Screen(self.callbacks)
        self.screen.refresh()

        self.glog_handler = GraphicalLog(self.callbacks, self.screen)
        rootlog = logging.getLogger()
        rootlog.addHandler(self.glog_handler)

        # Flush out any pre-graphical errors
        for err in self.early_errors:
            log.error(err)

    def write(self, cmd, args, conn=0):
        if not self.disconn:
            self.backend.write(cmd, args, conn)
        else:
            log.debug("Disconnected. Discarding %s - %s" % (cmd, args))

    def disconnected(self):
        self.disconn = CONN_NEED_NOTIFY

    def reconnected(self):
        self.reconn = CONN_NEED_NOTIFY

    def opt(self, args):
        t, r = self._first_term(args,
                lambda : self.screen.input_callback("opt: "))
        if not t:
            return (False, None, None)

        # Ensure that that option exists. We just use self.config because we
        # know we're not changing any values.

        try:
            self._get_opt(t, self.config)
            return (True, t, r)
        except:
            log.error("Unknown option: %s" % t)
            return (False, None, None)

    @command_format([("opt","opt")])
    def cmd_toggle(self, **kwargs):
        c = self.get_conf()

        val = self._get_opt(kwargs["opt"], c)

        if type(val) != bool:
            log.error("Option %s isn't boolean." % kwargs["opt"])
            return

        self._set_opt(kwargs["opt"], not val, c)
        self.set_conf(c)

    def switch_tags(self, tag1, tag2):
        c = self.get_conf()

        t1_idx = c["tagorder"].index(tag1.tag)
        t2_idx = c["tagorder"].index(tag2.tag)

        c["tagorder"][t1_idx] = tag2.tag
        c["tagorder"][t2_idx] = tag1.tag

        self.set_conf(c)

        self.eval_tags()

    # This accepts arbitrary strings, but gives the right prompt.
    def transform(self, args):
        if not args:
            args = self.screen.input_callback("transform: ")
        return (True, args, None)

    # Setup a permanent, config based transform.
    @command_format([("transform","transform")])
    def cmd_transform(self, **kwargs):
        d = { "defaults" : { "global_transform" : kwargs["transform"] } }
        self.write("SETCONFIGS", d)
        self._refresh()

    # Setup a temporary, per socket transform.
    @command_format([("transform","transform")])
    def cmd_temp_transform(self, **kwargs):
        self.write("TRANSFORM", kwargs["transform"])
        self._refresh()

    @command_format([])
    def cmd_reconnect(self, **kwargs):
        self.backend.reconnect()

    @command_format([])
    def cmd_refresh(self, **kwargs):
        self._refresh()

    def _refresh(self):
        for tag in self.vars["curtags"]:
            tag.reset()
            self.write("ITEMS", [ tag.tag ])

    def winch(self):
        self.winched = True

    def tick(self):
        self.ticked = True

    def do_tick(self):
        self.ticked = False

        if not self.config["update"]["auto"]["enabled"]:
            return

        if self.update_interval <= 0:
            if self.updates:
                self.write("ITEMS", self.updates)

            self.update_interval =\
                    self.config["update"]["auto"]["interval"]
            self.updates = []
        else:
            self.update_interval -= 1

    def key(self, k):
        r = CommandHandler.key(self, k)
        if r:
            return r
        return self.screen.key(k)

    @command_format([("key", "named_key"),("cmdstring","string_or_not")])
    def cmd_bind(self, **kwargs):
        if not self.screen.bind(kwargs["key"], kwargs["cmdstring"]) and\
            not self.bind(kwargs["key"], kwargs["cmdstring"]):
            log.info("%s is unbound." % (kwargs["key"],))

    @command_format([("tags","string_or_not")])
    def cmd_tagregex(self, **kwargs):
        c = self.get_conf()
        if not kwargs["tags"]:
            log.info("tags = %s" % c["tags"])
        else:
            c["tags"] = kwargs["tags"]
        self.set_conf(c)
        self.eval_tags()

    def cmdescape(self, cmd):
        escaped = False
        r = ""
        for c in cmd:
            if escaped:
                r += c
                escaped = False
            elif c == "\\":
                escaped = True
            else:
                r += c
        return r.rstrip()

    def cmdsplit(self, cmd):
        r = escsplit(cmd, " &")

        # lstrip all commands because we
        # want to use .startswith instead of a regex.
        return [ s.lstrip() for s in r ]

#    def run(self):
#        import cProfile
#        cProfile.runctx("self._run()", globals(), locals(), "canto-out")

    def run(self):
        while True:
            for tag in self.callbacks["get_var"]("alltags"):
                tag.sync(True)
            self.screen.refresh()
            self.screen.redraw()

#            if self.ticked:
#                self.do_tick()

            # Turn signals into commands:
#            if self.reconn == CONN_NEED_NOTIFY:
#                priority.insert(0, ("INFO", self.reconnect_message))
#                self.disconn = 0
#                self.reconn = CONN_NOTIFIED
#                self.daemon_init()
#            elif self.disconn == CONN_NEED_NOTIFY:
#                priority.insert(0, ("EXCEPT", self.disconnect_message))
#                self.reconn = 0
#                self.disconn = CONN_NOTIFIED
#            if self.winched:
#                self.winched = False
#                # CMD because it's handled lower, by Screen
#                priority.insert(0, ("CMD", "resize"))

#            if priority:
#                cmd = priority[0]
#                priority = priority[1:]
#            elif command_string:
#                cmd = command_string[0]
#                command_string = command_string[1:]
#            else:
#                cmd = None

#                try:
#                    cmd = self.input_queue.get(True, 0.1)
#                except Empty:
#                    pass

#                try:
#                    if not cmd:
#                        cmd = self.backend.prio_responses.get(True, 0.1)
#                except Empty:
#                   pass

#                try:
#                    if not cmd:
#                        cmd = self.backend.responses.get(True, 0.1)
#                except Empty:
#                    continue

#            if cmd[0] == "KEY":
#                resolved = self.key(cmd[1])
#                if not resolved:
#                    continue
#                cmd = ("CMD", resolved)

#            # User command
#            if cmd[0] == "CMD":
#                log.debug("CMD: %s" % (cmd[1],))

                # Sub in a user command on the fly.
#                if cmd[1] == "command":
#                    cmd = ("CMD", self.screen.input_callback(":"))
#                    log.debug("command resolved to: %s" % cmd[1])

#                cmds = self.cmdsplit(cmd[1])

                # If this is actually multiple commands,
                # then append them to the priority queue
                # and continue to execute them one at a time.

#                if len(cmds) > 1:
#                    log.debug("single command split into: %s" % cmds)
#                    command_string.extend([("CMD", c) for c in cmds])
#                    continue

#                if " " in cmd[1]:
#                    basecmd, args = cmd[1].split(" ", 1)
#                else:
#                    basecmd = cmd[1]
#                    args = ""

#                if basecmd in self.aliases:
#                    log.debug("resolved '%s' to '%s'" %\
#                            (basecmd, self.aliases[basecmd]))
#                    basecmd = self.aliases[basecmd]

#                fullcmd = basecmd
#                if args:
#                    fullcmd += " " + args

#                fullcmd = self.cmdescape(fullcmd)

#                if fullcmd in ["quit", "exit"]:
#                    rootlog = logging.getLogger()
#                    rootlog.removeHandler(self.glog_handler)
#                    call_hook("curses_exit", [])
#                    self.screen.exit()
#                    if self.config["kill_daemon_on_exit"]:
#                       self.write("DIE", "")
#                    self.backend.exit()
#                    return

#                r = self.command(fullcmd)
#                if r == None:
#                    r = self.screen.command(fullcmd)

#                if r == False:
#                    log.debug("Command string canceled: %s" %\
#                            (command_string,))
#                    command_string = []
#            else:
#                protfunc = "prot_" + cmd[0].lower()
#                if hasattr(self, protfunc):
#                    getattr(self, protfunc)(cmd[1])

    def get_opt_name(self):
        return "main"
