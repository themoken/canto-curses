# Smart Link Plugin
# by Jack Miller
# v1.0

# Allow links to be fetched to disk and then run a smarter handler on it

# Use :fetch instead of :goto to use these handlers.

# HANDLERS is a list of handlers, specified like:

HANDLERS = [
    { "match-url" : ".*\\.mp3$",
      "handler" : "mplayer",
      "regex" : True,
    },
    { "match-file" : "image data",
      "handler" : "feh",
    },
    { "match-file" : "PDF",
      "handler" : "evince",
    }
]

# Each handler will either have a 'match-url' setting or a 'match-file' setting.

# These will be considered regexes if 'regex' is True, it defaults to False,
# which will use a basic string search.

# 'match-url' should be used for network capable helpers, like mplayer, and if
# a match-url match is found, canto-curses won't download the file.

# If nothing matches ANY 'match-url' handler, then the file is downloaded and
# `file` is run on it. 'match-file' handlers are then checked against that
# output.

# If no handlers match, then your default browser is used, as if you had used
# :goto instead of :fetch.

# Matches are searched in order (except url matches always come before file
# matches). So if you want to, say, open PNGs in one sort of handler, and all
# other images in another handler, you could list something like

# { "match-file" : "PNG image data",
#   "handler" : "png-helper",
# },
# { "match-file" : "image data",
#   "handler" : "other-helper",
# }

# You may also specify a "pause" setting if you want to use other terminal
# programs without canto getting in the way.

# { "match-file" : "Audio data",
#   "handler" : "mocp",
#   "pause" : True,
# }

# If you have no match-file handlers listed, the file will not be downloaded.

from canto_next.plugins import check_program

check_program("canto-curses")

from canto_next.hooks import on_hook

from canto_curses.taglist import TagListPlugin
from canto_curses.reader import ReaderPlugin
from canto_curses.command import register_commands

from threading import Thread
import subprocess
import tempfile
import logging
import urllib
import shlex
import sys
import re
import os

log = logging.getLogger("SMARTLINK")

class SmartLinkThread(Thread):
    def __init__(self, base_obj, href):
        Thread.__init__(self, name="Smart Link: %s" % href)
        self.base_obj = base_obj
        self.href = href
        self.daemon = True

    def run(self):
        got_handler = None
        file_handlers = []

        for handler in HANDLERS:
            # If there's no handler defined, we don't care if it's a match
            if "handler" not in handler:
                log.error("No handler binary defined for: %s" % handler)
                continue

            if "regex" in handler and handler["regex"] == True:
                handler['regex'] = True
            else:
                handler['regex'] = False

            if "match-url" in handler:
                got_handler = self.try_handler(handler, "url", self.href)
                if got_handler:
                    break
            elif "match-file" in handler:
                file_handlers.append(handler)
            else:
                log.error("No match-url or match-file in handler %s" % handler)
        else:
            # We didn't find a matching URL handler.

            # No file_handlers present, don't bother to download, create
            # a default browser handler.

            if file_handlers:
                try:
                    tmpnam = self.grab_it()
                except Exception as e:
                    log.error("Couldn't download file: %s" % e)

                    # If we couldn't get the file, skip all of these
                    file_handlers = []
                else:
                    try:
                        fileoutput = subprocess.check_output("file %s" % shlex.quote(tmpnam), shell=True)
                        fileoutput = fileoutput.decode()
                    except Exception as e:
                        log.error("Couldn't get file output: %s" % e)

                        # If we couldn't get the `file` output, also skip
                        file_handlers = []

            for f_handler in file_handlers:
                log.debug("f_handler: %s", f_handler)
                got_handler = self.try_handler(f_handler, "file", fileoutput)
                if got_handler:
                    self.href = tmpnam
                    break
            else:
                conf = self.base_obj.callbacks["get_conf"]()
                got_handler = { 
                        "handler" : conf["browser"]["path"],
                        "text" : conf["browser"]["text"]
                }

        # Okay, so at this point we have self.href, which is either the URL or
        # the temporary file path, and got_handler telling us what to invoke an
        # how.

        log.info("Opening %s with %s" % (self.href, got_handler["handler"]))

        # Make sure that we quote href such that malicious URLs like
        # "http://example.com & rm -rf ~/" won't be interpreted by the shell.

        href = shlex.quote(self.href)

        pause = False
        if "pause" in got_handler and got_handler["pause"]:
            self.base_obj.callbacks["pause_interface"]()
            pause = True

        path = got_handler["handler"]
        if "%u" in path:
            path = path.replace("%u", href)
        elif href:
            path = path + " " + href

        pid = os.fork()

        if not pid:
            # A lot of programs don't appreciate having their fds closed, so
            # instead we dup them to /dev/null.

            fd = os.open("/dev/null", os.O_RDWR)
            os.dup2(fd, sys.stderr.fileno())

            if not pause:
                os.setpgid(os.getpid(), os.getpid())
                os.dup2(fd, sys.stdout.fileno())
                os.dup2(fd, sys.stdin.fileno())

            os.execv("/bin/sh", ["/bin/sh", "-c", path])

            # Just in case.
            sys.exit(0)

        # Parent process only cares if we should wait for the process to finish

        elif pause:
            os.waitpid(pid, 0)
            self.base_obj.callbacks["unpause_interface"]()

    def try_handler(self, handler, suffix, content):
        got_match = False
        element = "match-" + suffix

        # We know these elements exist, from above
        if not handler["regex"]:
            got_match = handler[element] in content
        else:
            try:
                got_match = re.match(handler[element], content)
            except Exception as e:
                log.error("Failed to do %s match: $s" % (suffix, e))

        if got_match:
            return handler

    def grab_it(self):
        # Prepare temporary files

        # Get a base filename (sans query strings, etc.) from the URL

        tmppath = urllib.parse.urlparse(self.href).path
        fname = os.path.basename(tmppath)

        # Grab a temporary directory. This allows us to create a file with
        # an unperturbed filename so scripts can freely use regex /
        # extension matching in addition to mimetype detection.

        tmpdir = tempfile.mkdtemp(prefix="canto-")
        tmpnam = tmpdir + '/' + fname

        log.debug("Downloading %s to %s", self.href, tmpnam)

        on_hook("curses_exit", lambda : (os.unlink(tmpnam)))
        on_hook("curses_exit", lambda : (os.rmdir(tmpdir)))

        tmp = open(tmpnam, 'w+b')

        # Set these because some sites think python's urllib is a scraper and
        # 403 it.

        extra_headers = { 'User-Agent' :\
                'Canto/0.9.0 + http://codezen.org/canto-ng'}

        request = urllib.request.Request(self.href, headers = extra_headers)

        # Grab the HTTP info / prepare to read.
        response = urllib.request.urlopen(request)

        # Grab in kilobyte chunks to avoid wasting memory on something
        # that's going to be immediately written to disk.

        while True:
            r = response.read(1024)
            if not r:
                break
            tmp.write(r)

        response.close()
        tmp.close()

        return tmpnam

class TagListSmartLink(TagListPlugin):
    def __init__(self, taglist):
        self.taglist = taglist
        self.plugin_attrs = {}

        cmds = {
            "fetch" : (self.cmd_fetch_link, ["item-list"], "Fetch link"),
        }

        register_commands(taglist, cmds)

        taglist.bind('f', 'fetch')

    def cmd_fetch_link(self, items):
        SmartLinkThread(self.taglist, items[0].content["link"]).start()
        
class ReaderSmartLink(ReaderPlugin):
    def __init__(self, reader):
        self.reader = reader
        self.plugin_attrs = {}

        cmds = {
            "fetch" : (self.cmd_fetch_link, ["link-list"], "Fetch link"),
        }

        register_commands(reader, cmds)

        reader.bind('f', 'fetch')

    def cmd_fetch_link(self, link):
        SmartLinkThread(self.reader, link[0][1]).start()
