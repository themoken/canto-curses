# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

import logging
import curses

log = logging.getLogger("COMMAND")

def command_format(types):
    def cf(fn):
        def cfdec(self, **kwargs):

            rem = kwargs["args"]
            realkwargs = {}

            for kw, validator in types:
                validator = getattr(self, validator)
                valid, result, rem = validator(rem.lstrip())
                if not valid:
                    log.debug("Couldn't properly parse %s" % kwargs["args"])
                    return

                realkwargs[kw] = result

            return fn(self, **realkwargs)
        return cfdec
    return cf

class CommandHandler():

    def command(self, command):
        for attr in dir(self):
            if attr.startswith("cmd_"):
                name = attr[4:].replace("_","-")
                if command == name or command.startswith(name + " "):
                    func = getattr(self, attr)
                    func(args=command[len(name):])
                    return True
        return False

    def key(self, k):

        # Translate numeric key into config friendly keyname

        optname = self.get_opt_name() + ".key."
        if k < 256:
            k = chr(k)

            # Need translation because they're invisible in config
            if k == " ":
                k = "space"
            elif k == "\t":
                k = "tab"

            # Need translation because they're special characters in config
            # (i.e. they end the name of the setting and start the setting
            # itself)

            elif k == "=":
                k = "equal"
            elif k == ":":
                k = "colon"

            optname += k
        else:
            for attr in dir(curses):
                if not attr.startswith("KEY_"):
                    continue

                if k == getattr(curses, attr):
                    optname += attr[4:].lower()

        log.debug("trying key: %s" % optname)
        r = self.callbacks["get_opt"](optname)

        # None happens if the option is unset
        # "None" can be used by the user to ignore
        # a keybind without any chatter.
        if r and r != "None":
            return r

        return None

    def _listof_int(self, args, maxint, prompt):
        if not args:
            args = prompt()

        if args == "*":
            return range(0, maxint)

        if " " in args:
            terms = args.split(" ")
        elif "," in args:
            terms = args.split(",")
        else:
            terms = [args]

        r = []
        for term in terms:
            if "-" in term:
                a, b = term.split("-",1)
                try:
                    a = int(a)
                    b = int(b)
                except:
                    log.error("Can't parse %s as range" % term)
                    continue
                r.extend(range(min(a, maxint), min(b + 1, maxint)))
            else:
                try:
                    term = int(term)
                except:
                    log.error("Can't parse %s as integer" % term)
                    continue
                if term < maxint:
                    r.append(term)
        return r

    def _int(self, args, prompt):
        t, r = self._first_term(args, prompt)
        try:
            t = int(t)
        except:
            log.error("Can't parse %s as integer." % t)
            return (None, None)
        return (t, r)

    def _first_term(self, args, prompt):
        if not args:
            args = prompt().split(" ")
            if len(args) > 1:
                log.error("Ignoring extra characters: %s" % " ".join(args[1:]))
            return (args[0], "")

        if " " not in args:
            return (args, "")
        args = args.split(" ", 1)
        return (args[0], args[1])
