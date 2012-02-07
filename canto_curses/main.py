# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.client import CantoClient
from canto_next.plugins import try_plugins

from .gui import CantoCursesGui

from threading import Thread
from queue import Queue

import logging

logging.basicConfig(
        filemode = "w",
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

        # Response queue.
        self.responses = None

        self.short_args = 'vl'
        optl = self.common_args(self.short_args)

        if optl == -1:
            sys.exit(-1)

        if self.args(optl):
            sys.exit(-1)

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

        # Make sure we have permissions on the relevant, non-daemon files in
        # the target directory (None of these will be used until we set_log)

        if self.ensure_paths():
            sys.exit(-1)

        self.set_log()
        log.info("Canto-curses started.")

        # Evaluate anything in the target /plugins directory.
        try_plugins(self.conf_dir)

    def args(self, optlist):
        for opt, arg in optlist:
            if opt in ["-v"]:
                rootlog = logging.getLogger()
                rootlog.setLevel(max(rootlog.level - 10,0))
            if opt in ["-l"]:
                self.log_fname_pid = True
        return 0

    # The response_thread takes anything received from the socket and puts it
    # onto the responses queue. This queue is expected to be used by the Gui
    # object as its main event queue.

    def response_thread(self):
        try:
            while self.response_alive:
                r = self.read()

                # HUP
                if r == 16:
                    self.response_alive = False
                    break
                if r:
                    self.responses.put(r)

        except Exception as e:
            log.error("Response thread exception: %s" % (e,))

        log.debug("Response thread exiting.")

    def start_rthread(self):
        self.response_alive = True

        # If we're reconnecting, don't recreate Queue
        if not self.responses:
            self.responses = Queue()

        # Thead *must* be running before gui instantiated
        # so the __init__ can ram some discovery requests through.

        thread = Thread(target=self.response_thread)
        thread.daemon = True
        thread.start()

    def start_gthread(self):
        thread = Thread(target=self.gui.run)
        thread.daemon = True
        thread.start()

    def alarm(self, a = None, b = None):
        self.gui.tick()
        signal.alarm(1)

    def winch(self, a = None, b = None):
        self.gui.winch()

    def sigusr1(self, a = None, b = None):
        pass

    def child(self, a = None, b = None):
        try:
            while True:
                pid, status = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
                log.debug("CHLD %d has died: %d" % (pid, status))
        except Exception as e:
            if e.errno == errno.ECHILD:
                log.debug("CHLD no children?")
            else:
                raise

    def disconnected(self, conn):
        self.response_alive = False
        self.gui.disconnected()

    def reconnect(self):
        try:
            self.connect()
        except Exception as e:
            log.error("Error reconnecting: %s" % e)
            self.gui.disconnected()
        else:
            self.start_rthread()
            self.gui.reconnected()

    def run(self):
        # Initial response thread setup.
        self.start_rthread()

        # Initial Gui setup.
        self.gui = CantoCursesGui(self)
        self.start_gthread()

        # Initial signal setup.
        signal.signal(signal.SIGUSR1, self.sigusr1)
        signal.signal(signal.SIGWINCH, self.winch)
        signal.signal(signal.SIGALRM, self.alarm)
        signal.signal(signal.SIGCHLD, self.child)
        signal.alarm(1)

        # Block on signals.
        while not self.done:
            signal.pause()

    # Exit signals ourselves with SIGUSR1 so that the above
    # signal.pause() call will wake up and let run() return.

    def exit(self):
        self.done = True
        os.kill(self.pid, signal.SIGUSR1)

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
            tb = traceback.format_exc(e)
            log.error("Exiting on exception:")
            log.error("\n" + "".join(tb))

        self.response_alive = False

        log.info("Exiting.")
        sys.exit(0)

    def __init__(self):
        self.start()
