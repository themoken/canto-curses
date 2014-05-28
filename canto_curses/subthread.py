# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
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

        self.wlock = Lock()

        # Start up our own connection
        self.conn = backend.connect()
        self.prot_thread = None
        self.alive = False

    def prot_except(self, exception):
        log.error("%s" % exception)

    def prot_errors(self, errors):
        for key in list(errors.keys()):
            val = errors[key][1][0]
            symptom = errors[key][1][1]
            log.error("%s = %s : %s" % (key, val, symptom))

    def prot_info(self, info):
        log.info("%s" % info)

    def write(self, cmd, args):
        self.wlock.acquire()
        r = self.backend.do_write(self.conn, cmd, args)
        self.wlock.release()

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
                else:
                    log.error("Unknown config response?")
                    log.error("%s - %s" % (cmd, args))
        except Exception as e:
            log.error("Config thread exception: %s" % (e,))
            log.error(''.join(traceback.format_exc()))

        log.info("Config thread exiting.")

    def start_pthread(self):
        self.prot_thread = Thread(target=self.pthread)
        self.prot_thread.daemon = True
        self.prot_thread.start()

