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

        self.script = script

    def connect(self):
        return 0

    def do_write(self, conn, cmd, args):
        print("%s write %s - %s" % (self.prefix, cmd, args))
        
        found_response = False
        r = None

        for key in self.script.keys():
            if key == cmd:
                responses = self.script[key]
                if repr(args) in responses:
                    found_response = True
                    r = responses[args]
                    break
                elif "*" in responses:
                    found_response = True
                    r = responses["*"]
                    break
        if not found_response:
            return

        print(" -> queued response %s" % (r,))

        self.lock.acquire()
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

    def inject(self, cmd, args):
        self.lock.acquire()
        self.responses.append({ cmd : args })
        self.lock.release()

class Test(object):
    def __init__(self, name):
        self.name = name
        self.run()
    
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
