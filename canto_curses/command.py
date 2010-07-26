# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

import logging

log = logging.getLogger("COMMAND")

import re

def command_format(pattern):
    r = re.compile(pattern)
    def cf(fn):
        def cfdec(self, **kwargs):

            # If this command has been parsed without error,
            # then just pass the args on to the next function

            if "error" in kwargs and not kwargs["error"]:
                return fn(self, **kwargs)

            m = r.match(kwargs["args"])

            if not m:
                kwargs["error"] = True
                return fn(self, **kwargs)

            gd = m.groupdict()

            # Do special subs

            for k in gd:
                if "_" in k:
                    handler, arg = k.split("_", 1)
                    gd[k] = getattr(self, handler)(arg, gd[k])
                else:
                    gd[k] = getattr(self, k)(gd[k])

                # If the handler still didn't fill it out
                # then error out for the next subcommand

                if gd[k] == None:
                    kwargs["error"] = True
                    return fn(self, **kwargs)

            kwargs["error"] = False
            kwargs.update(gd)
            return fn(self, **kwargs)

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
    def input(self, prompt):
        pass

    def handle_type(self, typ, args):
        log.debug("handle_type: %s %s" % (typ, args))
        if typ.startswith("listof_"):
            typ = typ.split("_", 1)[1]
            try:
                args = eval("[" + args + "]")
            except:
                return None

            if typ == "int":
                for i in args:
                    if type(i) != int:
                        return None

                return args
            else:
                return None
        elif typ == "string":
            return args
        elif typ == "int":
            try:
                args = int(args)
                return args
            except:
                return None
        else:
            return None

    def prompt(self, args, value):
        prompt, typ = args.split("_", 1)
        if not value:
            value = self.input(prompt + ": ")
        return self.handle_type(typ, value)
