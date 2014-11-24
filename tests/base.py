from canto_next.remote import access_dict

from threading import Lock
import traceback
import logging

logging.basicConfig(
    format = "%(message)s",
    level = logging.DEBUG
)

import time

# Like main.py, except instead of communicating with a real server, it reads
# from a script.

class TestBackend(object):
    def __init__(self, prefix, script):
        self.prefix = prefix
        self.location_args = ""

        self.lock = Lock()
        self.responses = []
        self.procd = []

        self.script = script

    def connect(self):
        return 0

    def do_write(self, conn, cmd, args):
        print("%s write %s - %s" % (self.prefix, cmd, args))
        
        found_response = False
        resps = []

        for key in self.script.keys():
            if key == cmd:
                responses = self.script[key]
                if repr(args) in responses:
                    found_response = True
                    resps.extend(responses[args])
                    break
                elif "*" in responses:
                    found_response = True
                    resps.extend(responses["*"])
                    break
        if not found_response:
            return

        self.lock.acquire()
        for r in resps:
            print(" -> queued response %s" % (r,))
            self.responses.append(r)
        self.lock.release()

    def do_read(self, conn):
        self.lock.acquire()
        while self.responses == []:
            self.lock.release()
            time.sleep(0.1)
            self.lock.acquire()

        r = self.responses[0]
        self.responses = self.responses[1:]
        self.lock.release()

        print("%s read %s" % (self.prefix, r))
        return r

    def processed(self, cmd, args):
        self.lock.acquire()
        self.procd.append((cmd, args))
        self.lock.release()

    def inject(self, cmd, args):
        self.lock.acquire()
        self.responses.append((cmd, args))
        self.lock.release()

        while True:
            got_it = False
            self.lock.acquire()
            if self.procd != []:
                if self.procd[0] == (cmd, args):
                    got_it = True
                self.procd = self.procd[1:]
            self.lock.release()

            if got_it:
                return

class Test(object):
    def __init__(self, name):
        self.name = name
        self.run()

    def compare_flags(self, value):
        if self.flags != value:
            raise Exception("Expected flags %d - got %d" % (value, self.flags))

    def compare_config(self, config, var, evalue):
        ok, got = access_dict(config, var)
        if not ok:
            raise Exception("Couldn't get %s?" % var)
        if got != evalue:
            raise Exception("Expected %s == %s - got %s" % (var, evalue, got))

    def compare_var(self, var, evalue):
        if hasattr(self, var):
            val = getattr(self, var)
            if val != evalue:
                raise Exception("Expected self.%s == %s - got %s" % (var, evalue, val))
        else:
            raise Exception("Couldn't get self.%s?" % var)

    def run(self):
        print("STARTING %s\n" % self.name)

        try:
            r = self.check()
        except Exception as e:
            print("\n%s - FAILED ON EXCEPTION" % self.name)
            print(traceback.format_exc())
            return 1

        if r == True:
            print("\n%s - PASSED\n" % self.name)
            return 0

        print("\n%s - FAILED\n" % self.name)
        return 1

    def check(self):
        pass
