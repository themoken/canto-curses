# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2016 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

CANTO_PROTOCOL_COMPATIBLE = 0.9

from canto_next.client import CantoClient
from canto_next.plugins import try_plugins, set_program
from canto_next.rwlock import alllocks
from canto_next.hooks import call_hook

from .config import config, finalize_eval_settings
from .tagcore import tag_updater, alltagcores
from .gui import CantoCursesGui, GraphicalLog

from threading import Thread
from queue import Queue

import logging

logging.basicConfig(
        format = "%(asctime)s : %(name)s -> %(message)s",
        datefmt = "%H:%M:%S",
        level = logging.INFO
)

log = logging.getLogger("CANTO-CURSES")

import traceback
import locale
import getopt
import signal
import errno
import fcntl
import time
import sys
import os

# It's the CantoCurses class' responsibility to provide the subsequent Gui
# object with a solid foundation with other components. This includes parsing
# command line arguments, starting a canto-daemon instance if necessary, signal
# handling, and wrapping the socket communication.

class CantoCurses(CantoClient):

    def init(self):

        # For good curses behavior.
        locale.setlocale(locale.LC_ALL, '')

        # Used for GUI-signalled death.
        self.pid = os.getpid()
        self.done = False

        # Whether or not to append pid to logfile
        # (debug option)
        self.log_fname_pid = False

        version = "canto-curses " + VERSION + " " + GIT_HASH
        optl = self.common_args('hl', ["help"], version)
        if optl == -1:
            sys.exit(-1)

        if self.args(optl):
            sys.exit(-1)

        rootlog = logging.getLogger()
        rootlog.setLevel(max(rootlog.level - 10 * self.verbosity,0))

        self.glog_handler = GraphicalLog()

        try:
            if self.port < 0:
                # If we're running locally, ensure daemon is running
                self.start_daemon()
                CantoClient.__init__(self, self.socket_path)
            else:
                CantoClient.__init__(self, None,\
                        port = self.port, address = self.addr)
        except Exception as e:
            log.error("Error: %s" % e)
            sys.exit(-1)

        # __init__ above started one connection, start another
        # for priority stuff.

        self.connect()

        # Make sure we have permissions on the relevant, non-daemon files in
        # the target directory (None of these will be used until we set_log)

        if self.ensure_paths():
            sys.exit(-1)

        self.set_log()
        log.info(version)

        # Evaluate anything in the target /plugins directory.
        set_program("canto-curses")
        self.plugin_errors = try_plugins(self.conf_dir, self.plugin_default, self.disabled_plugins,
                self.enabled_plugins)


    def print_help(self):
        print("USAGE: canto-curses [options]")
        print("\t-h/--help\tThis help")
        print("\t-V/--version\tPrint version")
        print("\t-v/\t\tVerbose logging (for debug)")
        print("\t-D/--dir <dir>\tSet configuration directory.")
        print("\t-l\t\tAppend pid to log file name")
        print("\nPlugin control\n")
        print("\t--noplugins\t\t\t\tDisable plugins")
        print("\t--enableplugins 'plugin1 plugin2...'\tEnable single plugins (overrides --noplugins)")
        print("\t--disableplugins 'plugin1 plugin2...'\tDisable single plugins")
        print("\nNetwork control\n")
        print("NOTE: These should be used in conjunction with SSH port forwarding to be secure\n")
        print("\t-a/--address <IP>\tConnect to this address")
        print("\t-p/--port <port>\tConnect to this port")

    def args(self, optlist):
        for opt, arg in optlist:
            if opt in ["-h", "--help"]:
                self.print_help()
                return 1
            elif opt in ["-l"]:
                self.log_fname_pid = True
        return 0

    def winch(self, a = None, b = None):
        if self.gui.alive:
            self.gui.winch()

    def sigusr1(self, a = None, b = None):
        import threading

        held_locks = {}
        code = {}
        curthreads = threading.enumerate()

        for threadId, stack in sys._current_frames().items():
            name = str(threadId)
            for ct in curthreads:
                if ct.ident == threadId:
                    name = ct.name

            code[name] = ["NAME: %s" % name]
            for filename, lineno, fname, line in traceback.extract_stack(stack):
                code[name].append('FILE: "%s", line %d, in %s' % (filename, lineno, fname))
                if line:
                    code[name].append("  %s" % (line.strip()))

            held_locks[name] = ""
            for lock in alllocks:
                if lock.writer_id == threadId:
                    held_locks[name] += ("%s(w)" % lock.name)
                    continue
                for reader_id, reader_stack in lock.reader_stacks:
                    if reader_id == threadId:
                        held_locks[name] += ("%s(r)" % lock.name)

        for k in code:
            log.info('\n\nLOCKS: %s \n%s' % (held_locks[k], '\n'.join(code[k])))

        log.info("\n\nSTACKS:")
        for lock in alllocks:
            for (reader_id, reader_stack) in lock.reader_stacks:
                log.info("Lock %s (%s readers)" % (lock.name, lock.readers))
                log.info("Lock reader (thread %s):" % (reader_id,))
                log.info(''.join(reader_stack))

            for writer_stack in lock.writer_stacks:
                log.info("Lock %s (%s readers)" % (lock.name, lock.readers))
                log.info("Lock writer (thread %s):" % (lock.writer_id,))
                log.info(''.join(writer_stack))

        log.info("VARS: %s" % config.vars)
        log.info("OPTS: %s" % config.config)

    def child(self, a = None, b = None):
        try:
            while True:
                pid, status = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
                log.debug("CHLD %d has died: %d", pid, status)
        except Exception as e:
            if e.errno == errno.ECHILD:
                log.debug("CHLD no children?")
            else:
                raise

    def run(self):
        # We want this as early as possible
        signal.signal(signal.SIGUSR1, self.sigusr1)

        # Get config from daemon
        if not config.init(self, CANTO_PROTOCOL_COMPATIBLE):
            print("Invalid daemon version")
            print("Wanted: %s" % CANTO_PROTOCOL_COMPATIBLE)
            print("Got: %s" % config.version)
            sys.exit(-1)
        else:
            log.info("Version check passed: %s" % CANTO_PROTOCOL_COMPATIBLE)

        # Create Tags for each TagCore
        self.gui = CantoCursesGui(self, self.glog_handler)
        tag_updater.init(self)

        # Initial signal setup.
        signal.signal(signal.SIGWINCH, self.winch)
        signal.signal(signal.SIGCHLD, self.child)

        finalize_eval_settings()

        call_hook("curses_start", [])

        if self.plugin_errors:
            log.error("The following error occurred loading plugins:\n\n%s" % self.plugin_errors)

        while self.gui.alive:
            self.gui.tick()
            time.sleep(1)

    def ensure_paths(self):
        if os.path.exists(self.conf_dir):
            if not os.path.isdir(self.conf_dir):
                log.error("Error: %s is not a directory." % self.conf_dir)
                return -1
            if not os.access(self.conf_dir, os.R_OK):
                log.error("Error: %s is not readable." % self.conf_dir)
                return -1
            if not os.access(self.conf_dir, os.W_OK):
                log.error("Error: %s is not writable." % self.conf_dir)
                return -1
        else:
            try:
                os.makedirs(self.conf_dir)
            except Exception as e:
                log.error("Exception making %s : %s" % (self.conf_dir, e))
                return -1
        return self.ensure_files()

    def ensure_files(self):
        logname = "curses-log"
        if self.log_fname_pid:
            logname += ".%d" % os.getpid()

        for f in [ logname ] :
            p = self.conf_dir + "/" + f
            if os.path.exists(p):
                if not os.path.isfile(p):
                    log.error("Error: %s is not a file." % p)
                    return -1
                if not os.access(p, os.R_OK):
                    log.error("Error: %s is not readable." % p)
                    return -1
                if not os.access(p, os.W_OK):
                    log.error("Error: %s is not writable." % p)
                    return -1

        self.log_path = self.conf_dir + "/" + logname

    def set_log(self):
        f = open(self.log_path, "w")
        os.dup2(f.fileno(), sys.stderr.fileno())

    def start(self):
        try:
            self.init()
            self.run()
        except KeyboardInterrupt:
            pass

        except Exception as e:
            tb = traceback.format_exc()
            log.error("Exiting on exception:")
            log.error("\n" + "".join(tb))

        call_hook("curses_exit", [])
        log.info("Exiting.")
        sys.exit(0)

    def __init__(self):
        self.start()
