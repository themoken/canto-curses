# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

COMPATIBLE_VERSION = 0.4

from canto_next.plugins import Plugin
from canto_next.format import escsplit

from .tagcore import alltagcores
from .tag import Tag

from .locks import sync_lock
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

class CantoCursesGui():
    def __init__(self, backend):

        self.backend = backend

        self.update_interval = 0

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

        self.do_refresh = Event()

        self.graphical_thread = Thread(target = self.run_gui)
        self.graphical_thread.daemon = True
        self.graphical_thread.start()

        self.input_thread = Thread(target = self.run)
        self.input_thread.daemon = True
        self.input_thread.start()

        self.sync_timer = 1

    def tick(self):
        self.sync_timer -= 1
        if self.sync_timer <= 0:
            for tag in self.callbacks["get_var"]("alltags"):
                tag.sync(True)
            self.sync_timer = 60

    def cmdsplit(self, cmd):
        r = escsplit(cmd, " &")

        # lstrip all commands because we
        # want to use .startswith instead of a regex.
        return [ s.lstrip() for s in r ]

    def run(self):
        while True:
            r = self.screen.get_key()
            log.debug("KEY: %s" % r)

            # We got a key, now resolve it to a command
            f = self.screen.get_focus_list()
            for win in reversed(f):
                cmd = win.key(r)
                if cmd:
                    break
            else:
                continue

            cmds = self.cmdsplit(cmd)
            log.debug("Resolved to %s" % cmds)

            # Now actually issue the commands

            sync_lock.acquire_write()
            for cmd in cmds:
                for win in reversed(f):
                    if win.command(cmd):
                        break
            sync_lock.release_write()

            # Let the GUI thread process
            self.do_refresh.set()

    def run_gui(self):
        while True:
            self.do_refresh.wait()
            self.do_refresh.clear()

            sync_lock.acquire_write()
            if self.callbacks["get_var"]("needs_refresh"):
                self.screen.refresh()
            if self.callbacks["get_var"]("needs_redraw"):
                self.screen.redraw()
            sync_lock.release_write()

