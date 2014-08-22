# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2014 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import Plugin
from canto_next.format import escsplit

from .tagcore import tag_updater

from .locks import sync_lock
from .command import CommandHandler, cmd_execute, register_command
from .text import ErrorBox, InfoBox
from .config import config
from .screen import Screen

from threading import Thread, Event
import logging

log = logging.getLogger("GUI")

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

class CantoCursesGui(CommandHandler):
    def __init__(self, backend):
        CommandHandler.__init__(self)
        self.plugin_class = GuiPlugin
        self.update_plugin_lookups()

        self.backend = backend

        self.update_interval = 0

        self.do_gui = Event()

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
            "release_gui" : self.release_gui,
            "force_sync" : self.force_sync,
            "switch_tags" : config.switch_tags,
        }

        log.debug("Starting curses.")

        self.alive = True
        self.sync_timer = 1

        self.screen = Screen(self.callbacks)
        self.screen.refresh()

        self.graphical_thread = Thread(target = self.run_gui)
        self.graphical_thread.daemon = True
        self.graphical_thread.start()

        self.glog_handler = GraphicalLog(self.callbacks, self.screen)
        rootlog = logging.getLogger()
        rootlog.addHandler(self.glog_handler)

        register_command(self, "refresh", self.cmd_refresh, [], "Refetch everything from the daemon")
        register_command(self, "quit", self.cmd_quit, [], "Quit canto-curses")

        self.input_thread = Thread(target = self.run)
        self.input_thread.daemon = True
        self.input_thread.start()

    def force_sync(self):
        self.sync_timer = 0
        self.release_gui()

    def release_gui(self):
        self.do_gui.set()

    def tick(self):
        #log.debug("...tick...")
        self.sync_timer -= 1
        if self.sync_timer <= 0:
            self.release_gui()

    def winch(self):
        self.callbacks["set_var"]("needs_resize",  True)
        self.release_gui()

    def cmd_refresh(self):
        tag_updater.reset()
        tag_updater.update()
        self.sync_timer = 0
        self.release_gui()

    def cmd_quit(self):
        self.alive = False

    def cmdsplit(self, cmd):
        r = escsplit(cmd, " &")

        # lstrip all commands because we
        # want to use .startswith instead of a regex.
        return [ s.lstrip() for s in r ]

    def issue_cmd(self, winlist, cmd):
        sync_lock.acquire_write()
        r = cmd_execute(cmd)
        sync_lock.release_write()
        return r

    def run(self):
        while self.alive:
            r = self.screen.get_key()

            # Get a list of all command handlers
            f = [self] + self.screen.get_focus_list()

            # We got a key, now resolve it to a command
            for win in reversed(f):
                cmd = win.key(r)
                if cmd:
                    break
            else:

                # Dismiss info box on any unbound key.

                if self.callbacks["get_var"]("info_msg"):
                    self.callbacks["set_var"]("info_msg", "")
                    self.release_gui()
                continue

            cmds = self.cmdsplit(cmd)
            log.debug("Resolved to %s" % cmds)

            # Now actually issue the commands

            for cmd in cmds:

                okay = False

                # Command is our one hardcoded command because it's special, and also shouldn't invoke itself.
                if cmd == "command":
                    subcmd = self.screen.input_callback(':')
                    log.debug("Got %s from user command" % subcmd)
                    subcmds = self.cmdsplit(subcmd)
                    for subcmd in subcmds:
                        okay = self.issue_cmd(reversed(f), subcmd)
                        if not okay:
                            break
                else:
                    okay = self.issue_cmd(reversed(f), cmd)

                if not okay:
                    break

            # Let the GUI thread process, or realize it's dead.
            self.release_gui()

    def run_gui(self):
        while True:
            self.do_gui.wait()
            self.do_gui.clear()
            log.debug("gui thread released")

            if not self.alive:

                # Remove graphical log handler so log.infos don't screw up the
                # screen after it's dead.

                rootlog = logging.getLogger()
                rootlog.removeHandler(self.glog_handler)
                self.screen.exit()
                break

            sync_lock.acquire_write()

            if self.sync_timer <= 0:
                log.debug("sync!")
                for tag in self.callbacks["get_var"]("alltags"):
                    tag.sync()
                self.sync_timer = 5

            # Resize implies a refresh and redraw
            if self.callbacks["get_var"]("needs_resize"):
                self.screen.resize()
                self.callbacks["set_var"]("needs_resize", False)
                self.callbacks["set_var"]("needs_refresh", False)
                self.callbacks["set_var"]("needs_redraw", False)

            if self.callbacks["get_var"]("needs_refresh"):
                self.screen.refresh()
                self.callbacks["set_var"]("needs_refresh", False)

            if self.callbacks["get_var"]("needs_redraw"):
                self.screen.redraw()
                self.callbacks["set_var"]("needs_redraw", False)

            sync_lock.release_write()

    def get_opt_name(self):
        return "main"
