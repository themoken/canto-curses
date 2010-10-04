# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.client import CantoClient
from canto_next.encoding import decoder
from gui import CantoCursesGui

from threading import Thread
from Queue import Queue

import logging

logging.basicConfig(
        filemode = "w",
        format = "%(asctime)s : %(name)s -> %(message)s",
        datefmt = "%H:%M:%S",
        level = logging.DEBUG
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

        if self.common_args():
            sys.exit(-1)

        self.start_daemon()

        # The daemon is running, init our base class, start trying to connect to
        # the daemon.

        try:
            CantoClient.__init__(self, self.socket_path)
        except Exception, e:
            log.error("Error: %s" % e)
            sys.exit(-1)

        # Make sure we have permissions on the relevant, non-daemon files in
        # the target directory (None of these will be used until we set_log)

        if self.ensure_files():
            sys.exit(-1)

        self.set_log()

        # Evaluate anything in the target /plugins directory.
        self.try_plugins()

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

        except Exception, e:
            log.error("Response thread exception: %s" % (e,))

        log.debug("Response thread exiting.")

    def start_rthread(self):
        self.response_alive = True
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
        signal.alarm(1)

        # Block on signals.
        while not self.done:
            signal.pause()

    # Exit signals ourselves with SIGUSR1 so that the above
    # signal.pause() call will wake up and let run() return.

    def exit(self):
        self.done = True
        os.kill(self.pid, signal.SIGUSR1)

    # For now, make sure the log is writable.

    def ensure_files(self):
        for f in [ "curses-log" ] :
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

        self.log_path = self.conf_dir + "/curses-log"

    def try_plugins(self):
        p = self.conf_dir + "/plugins"
        if not os.path.exists(p):
            log.info("No plugins directory found.")
            return
        if not os.path.isdir(p):
            log.warn("Plugins file is not directory.")
            return

        # Add plugin path to front of Python path.
        sys.path.insert(0, p)

        # Go ahead and import all .py
        for fname in os.listdir(p):
            if fname.endswith(".py"):
                try:
                    __import__(fname[:-3])
                except Exception, e:
                    tb = traceback.format_exc(e)
                    log.error("Exception importing file %s" % fname)
                    log.error("\n" + "".join(tb))

    def set_log(self):
        f = open(self.log_path, "w")
        os.dup2(f.fileno(), sys.stderr.fileno())

    def start(self):
        try:
            self.init()
            self.run()
        except KeyboardInterrupt:
            pass

        except Exception, e:
            tb = traceback.format_exc(e)
            log.error("Exiting on exception:")
            log.error("\n" + "".join(tb))

        self.write("PING", "")

        # Exploit the fact that requests are made in order and PING/PONG to
        # ensure all previous traffic is done. Strictly this is unnecessary, but
        # perhaps useful to know the daemon state on the way out.

        while True:
            if not self.responses.empty():
                r = self.responses.get()
                log.debug("r = %s" % (r, ))
                if r[0] == "PONG":
                    break
            if not self.response_alive:
                log.debug("Unabled to sync, connection closed.")
                break

        self.response_alive = False

        log.info("Exiting.")
        sys.exit(0)

    def __init__(self):
        self.start()
