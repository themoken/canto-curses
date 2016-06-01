# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2016 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

# SubThread is just a basic wrapper for a sub connection from the backend that
# dispatches to sub functions based on socket traffic

from threading import Thread, Lock
import traceback
import logging

log = logging.getLogger("SUBTHREAD")

class SubThread(object):
    def init(self, backend):
        self.backend = backend

        # Start up our own connection
        self.conn = backend.connect()
        self.prot_thread = None
        self.alive = False

    def prot_except(self, exception):
        log.error("%s" % exception)

    def prot_errors(self, errors):
        for key in list(errors.keys()):
            for val, error in errors[key]:
                log.error("%s = %s : %s" % (key, val, error))

    def prot_info(self, info):
        log.info("%s" % info)

    def write(self, cmd, args):
        return self.backend.do_write(self.conn, cmd, args)

    def read(self):
        return self.backend.do_read(self.conn)

    def pthread(self):
        self.alive = True

        try:
            while self.alive:
                r = self.read()

                if not r:
                    continue

                # HUP
                if r == 16:
                    self.alive = False
                    break

                cmd, args = r
                protfunc = "prot_" + cmd.lower()
                if hasattr(self, protfunc):
                    getattr(self, protfunc)(args)

                    # For test-suite
                    if hasattr(self.backend, "processed"):
                        self.backend.processed(cmd, args)

                else:
                    log.error("Unknown response?")
                    log.error("%s - %s" % (cmd, args))
        except Exception as e:
            log.error("Thread exception: %s" % (e,))
            log.error(''.join(traceback.format_exc()))

        log.info("Thread exiting - disconnected\nAny further changes will be forgotten!")

    def start_pthread(self):
        self.prot_thread = Thread(target=self.pthread)
        self.prot_thread.daemon = True
        self.prot_thread.start()

