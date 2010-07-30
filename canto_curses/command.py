# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

import logging

log = logging.getLogger("COMMAND")

def command_format(command, types):
    def cf(fn):
        def cfdec(self, **kwargs):

            # If this command has been parsed without error,
            # then just pass the args on to the next function

            if "error" in kwargs and not kwargs["error"]:
                return fn(self, **kwargs)

            if not kwargs["args"].startswith(command):
                kwargs["error"] = True
                return fn(self, **kwargs)

            rem = kwargs["args"][len(command):]
            realkwargs = {}

            for kw, validator in types:
                validator = getattr(self, validator)
                valid, result, rem = validator(rem.lstrip())
                if not valid:
                    kwargs["error"] = True
                    return fn(self, **kwargs)

                realkwargs[kw] = result

            realkwargs["error"] = False
            return fn(self, **realkwargs)
        return cfdec
    return cf

def generic_parse_error(fn):
    def gpedec(self, **kwargs):
        if kwargs["error"]:
            log.debug("Couldn't properly parse %s" % kwargs["args"])
            return
        return fn(self, **kwargs)
    return gpedec

class CommandHandler():

    def key(self, k):
        if k in self.keys:
            return self.keys[k]
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
