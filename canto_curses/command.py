# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import PluginHandler, Plugin, add_arg_transform

import traceback
import logging
import curses

log = logging.getLogger("COMMAND")

def command_format(types):
    def cf(fn):
        def _command_args(self, obj, **kwargs):
            rem = kwargs["args"]
            realkwargs = {}

            for kw, validator in types:
                if hasattr(obj, validator):
                    validator = getattr(obj, validator)
                elif hasattr(self, validator):
                    validator = getattr(self, validator)
                else:
                    log.warn("Couldn't get validator: %s, skipping" % validator)
                    continue

                valid, result, rem = validator(rem.lstrip())
                if not valid:
                    log.error("Couldn't properly parse %s" % kwargs["args"])
                    return

                realkwargs[kw] = result

            # Builtin command signature.
            if self == obj:
                return ([], realkwargs)

            # Plugin command signature.
            else:
                return ([obj], realkwargs)

        add_arg_transform(fn, _command_args)
        return fn
    return cf

class CommandPlugin(Plugin):
    pass

class CommandHandler(PluginHandler):
    def __init__(self):
        PluginHandler.__init__(self)

        self.plugin_class = CommandPlugin
        self.update_plugin_lookups()

        self.meta = False

    def command(self, command):
        if " " in command:
            command, args = command.split(" ", 1)
        else:
            args = ""

        attr = "cmd_" + command.replace("-","_")
        if hasattr(self, attr):
            try:
                func = getattr(self, attr)
                func(self, args = args)
            except Exception, e:
                tb = traceback.format_exc(e)
                log.error("Exception running command %s" % command)
                log.error("\n" + "".join(tb))
                log.error("Continuing...")

        return False

    # Verify a string is a possible key combination.

    def _input_key(self, key, depth = 0):
        if len(key) == 1 and ord(key) <= 255:
            return True
        if key in ["space", "tab"]:
            return True

        # Accept a Ctrl / Meta only once
        if depth == 0 and (key.startswith("C-") or key.startswith("M-")):
            return self._input_key(key[2:], 1)

        return ("key_" + key).upper() in dir(curses)

    def input_key(self, args, prompt):
        term, rem = self._first_term(args, prompt)

        if self._input_key(term):
            return (True, term, rem)
        return (False, None, None)

    def key(self, k):

        # Translate numeric key into config friendly keyname

        optname = self.get_opt_name() + ".key."

        # Add meta prefix.
        if self.meta:
            if k >= 64:
                k -= 64
                optname += "M-"
            self.meta = False

        if k > 255:
            for attr in dir(curses):
                if not attr.startswith("KEY_"):
                    continue

                if k == getattr(curses, attr):
                    optname += attr[4:].lower()

        # Remember meta for next keypress.
        elif curses.ascii.ismeta(k):
            self.meta = True
            return None
        else:
            # Add ctrl prefix.
            if curses.ascii.iscntrl(k):
                optname += "C-"
                k += 96

            k = chr(k)

            # Need translation because they're invisible

            if k == " ":
                k = "space"
            elif k == "\t":
                k = "tab"

            # Need translation because it's an escape

            elif k == "\\":
                k = "\\\\"

            optname += k

        log.debug("trying key: %s" % optname)

        try:
            r = self.callbacks["get_opt"](optname)
        except:
            r = None

        # None happens if the option is unset
        # "None" can be used by the user to ignore
        # a keybind without any chatter.
        if r and r != "None":
            return r

        return None

    # Convert a single argument into an integer, with special consideration
    # for $ as the end of the range and . as the current. This can throw an
    # exception on bad input.

    def _convert_special(self, item, curint, maxint):
        item = item.rstrip().lstrip()

        if item == "$" and maxint:
            return maxint - 1
        if item == "." and curint != None:
            return curint

        return int(item)

    def _listof_int(self, args, curint, maxint, prompt):
        if not args:
            args = prompt()

        if args == "*" and maxint:
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
                    a = self._convert_special(a, curint, maxint)
                    b = self._convert_special(b, curint, maxint)
                except:
                    log.error("Can't parse %s as range" % term)
                    continue
                if maxint:
                    r.extend(range(min(a, maxint), min(b + 1, maxint)))
                else:
                    r.extend(range(a, b + 1))
            else:
                try:
                    term = self._convert_special(term, curint, maxint)
                except:
                    log.error("Can't parse %s as integer" % term)
                    continue
                if not maxint or term < maxint:
                    r.append(term)
        return r

    def _int(self, args, curint, maxint, prompt):
        t, r = self._first_term(args, prompt)
        try:
            t = self._convert_special(t, curint, maxint)
        except:
            log.error("Can't parse %s as integer." % t)
            return (None, "")
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
