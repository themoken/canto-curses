# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2016 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import Plugin
from canto_next.format import escsplit

from .tag import alltags
from .tagcore import tag_updater

from .locks import sync_lock
from .command import CommandHandler, cmd_execute, register_command, register_alias
from .text import ErrorBox, InfoBox
from .config import config
from .screen import Screen

from threading import Thread, Event
import traceback
import logging

log = logging.getLogger("GUI")

class GraphicalLog(logging.Handler):

    # We want to be able to catch logging output before the screen is actually
    # initialized in curses, and callbacks etc. are setup

    def __init__(self):
        logging.Handler.__init__(self)
        self.deferred_logs = []
        self.callbacks = None

        rootlog = logging.getLogger()
        rootlog.addHandler(self)

    def init(self, callbacks, screen):
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

        # If we have no callbacks, GUI isn't initialized, assume that we only
        # want to have warns/errors displayed immediately on startup.

        if self.callbacks:
            quiet = self.callbacks["get_var"]("quiet")
        else:
            quiet = True
        if record.levelno == logging.INFO and quiet:
            return
        self.deferred_logs.append(record)

    # Call with sync_lock
    def flush_deferred_logs(self):
        for record in self.deferred_logs:
            if record.levelno in [ logging.INFO, logging.WARN ]:
                self._emit("info_msg", InfoBox, record)
            elif record.levelno == logging.ERROR:
                self._emit("error_msg", ErrorBox, record)
        self.deferred_logs = []

class GuiPlugin(Plugin):
    pass

class CantoCursesGui(CommandHandler):
    def __init__(self, backend, glog_handler):
        CommandHandler.__init__(self)
        self.plugin_class = GuiPlugin
        self.update_plugin_lookups()

        self.backend = backend
        self.winched = False

        self.update_interval = 0

        self.do_gui = Event()
        self.do_gui.set()

        self.working = False

        self.callbacks = {
            "set_var" : config.set_var,
            "get_var" : config.get_var,
            "set_conf" : config.set_conf,
            "get_conf" : config.get_conf,
            "set_tag_conf" : config.set_tag_conf,
            "get_tag_conf" : config.get_tag_conf,
            "set_defaults" : config.set_def_conf,
            "get_defaults" : config.get_def_conf,
            "set_feed_conf" : config.set_feed_conf,
            "get_feed_conf" : config.get_feed_conf,
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
        self.sync_requested = True
        self.tags_to_sync = []

        self.screen = Screen(self.callbacks)
        self.screen.refresh()
        self.screen.redraw()

        self.glog_handler = glog_handler
        self.glog_handler.init(self.callbacks, self.screen)

        self.graphical_thread = Thread(target = self.run_gui)
        self.graphical_thread.daemon = True
        self.graphical_thread.start()

        register_command(self, "refresh", self.cmd_refresh, [], "Refetch everything from the daemon", "Base")
        register_command(self, "update", self.cmd_update, [], "Sync with daemon", "Base")
        register_command(self, "quit", self.cmd_quit, [], "Quit canto-curses", "Base")

        self.input_thread = Thread(target = self.run)
        self.input_thread.daemon = True
        self.input_thread.start()

    def force_sync(self):
        self.sync_requested = True
        self.sync_timer = 0
        self.release_gui()

    def release_gui(self):
        self.do_gui.set()

    def tick(self):
        c = self.callbacks["get_conf"]()
        if c["update"]["auto"]["enabled"]:
            self.sync_timer -= 1
            if self.sync_timer <= 0:
                self.sync_requested = True
                self.release_gui()
                self.sync_timer = c["update"]["auto"]["interval"]
        else:
            self.sync_timer = 1
            if self.sync_requested:
                self.release_gui()

    def winch(self):
        self.winched = True
        if not self.do_gui.is_set():
            self.release_gui()

    def cmd_refresh(self):
        # Will trigger a hook on completion that will cause refresh
        tag_updater.update()

    def cmd_update(self):
        self.force_sync()

    def cmd_quit(self):
        self.alive = False

    def cmdsplit(self, cmd):
        r = escsplit(cmd, " &")

        # lstrip all commands because we
        # want to use .startswith instead of a regex.
        return [ s.lstrip() for s in r ]

    def issue_cmd(self, cmd):
        sync_lock.acquire_write()
        try:
            r = cmd_execute(cmd)
            return r
        except Exception as e:
            log.error("Exception: %s" % e)
            log.error(traceback.format_exc())
        finally:
            sync_lock.release_write()

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
                    self.callbacks["set_var"]("dispel_msg", False)
                    self.release_gui()
                continue

            cmds = self.cmdsplit(cmd)
            log.debug("Resolved to %s", cmds)

            # Now actually issue the commands

            for cmd in cmds:

                okay = False

                # Command is our one hardcoded command because it's special, and also shouldn't invoke itself.
                if cmd == "command":
                    subcmd = self.screen.input_callback(':')
                    log.debug("Got %s from user command", subcmd)
                    subcmds = self.cmdsplit(subcmd)
                    for subcmd in subcmds:
                        okay = self.issue_cmd(subcmd)
                        if not okay:
                            break
                else:
                    okay = self.issue_cmd(cmd)

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

            self.glog_handler.flush_deferred_logs()

            partial_sync = False
            self.working = True

            if self.sync_requested:
                self.tags_to_sync = alltags[:]
                self.sync_requested = False
            else:
                for tag in alltags:
                    if (tag not in self.tags_to_sync) and (tag.tagcore.was_reset or\
                            (len(tag) == 0 and len(tag.tagcore) != 0)):
                        self.tags_to_sync.append(tag)

            if self.tags_to_sync:
                self.tags_to_sync[0].sync()
                self.tags_to_sync = self.tags_to_sync[1:]
                partial_sync = True

            needs_resize = self.callbacks["get_var"]("needs_resize") or self.winched
            needs_refresh = self.callbacks["get_var"]("needs_refresh")
            needs_redraw = self.callbacks["get_var"]("needs_redraw")

            self.callbacks["set_var"]("needs_resize", False)
            self.callbacks["set_var"]("needs_refresh", False)
            self.callbacks["set_var"]("needs_redraw", False)

            # Resize implies a refresh and redraw
            if needs_resize:
                self.winched = False
                self.screen.resize()
            else:
                if needs_refresh:
                    self.screen.refresh()

                if needs_redraw:
                    self.screen.redraw()

            needs_resize = self.callbacks["get_var"]("needs_resize") or self.winched
            needs_refresh = self.callbacks["get_var"]("needs_refresh")
            needs_redraw = self.callbacks["get_var"]("needs_redraw")

            # If we weren't able to clear the condition, then
            # we'll drop locks and immediately go again.

            if needs_resize or needs_refresh or needs_redraw or partial_sync:
                self.do_gui.set()
            else:
                self.working = False

            sync_lock.release_write()

    def get_opt_name(self):
        return "main"
