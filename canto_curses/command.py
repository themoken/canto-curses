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
import shlex
import pipes

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
                    return False

                realkwargs[kw] = result

            # Builtin command signature.
            if self == obj:
                return ([], realkwargs)

            # Plugin command signature.
            else:
                return ([self], realkwargs)

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

        self.key_translations =\
                { '.' : "period",
                  '\t' : "tab",
                  "C-i" : "tab",
                  ' ' : "space",
                  "\\" : "\\\\" }

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
                r = func(self, args = args)
                # Consider returning None as OK
                if r == None:
                    return True
                return r
            except Exception as e:
                tb = traceback.format_exc()
                log.error("Exception running command %s" % command)
                log.error("\n" + "".join(tb))
                log.error("Continuing...")

        return None

    def translate_key(self, key):
        if key in self.key_translations:
            return self.key_translations[key]
        return key

    # Verify a string is a possible key combination.

    def _input_key(self, key, depth = 0):
        if len(key) == 1 and ord(key) <= 255:
            return True
        if key in self.key_translations:
            return True

        # Accept a Ctrl / Meta only once
        if depth == 0 and (key.startswith("C-") or key.startswith("M-")):
            return self._input_key(key[2:], 1)

        return ("key_" + key).upper() in dir(curses)

    def input_key(self, args, prompt):
        term, rem = self._first_term(args, prompt)
        if not term:
            return (False, None, None)
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
            keyname = ""
            # Add ctrl prefix.
            if curses.ascii.iscntrl(k):
                keyname += "C-"
                k += 96

            keyname += chr(k)
            optname += self.translate_key(keyname)

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
            return list(range(0, maxint))

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
                    r.extend(list(range(min(a, maxint), min(b + 1, maxint))))
                else:
                    r.extend(list(range(a, b + 1)))
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
        if not t:
            return (None, "")
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
            return (args[0].rstrip(), "")

        if " " not in args:
            return (args.rstrip(), "")
        args = args.split(" ", 1)
        return (args[0].rstrip(), args[1])

    # Grab a single string, potentially quoted or space delimited and pass the
    # rest.

    def single_string(self, args, prompt):
        if not args:
            args = prompt()

        r = shlex.split(args)

        # I wish shlex.split took a max so I didn't have to zip them up
        # again with pipes.quote.

        if r:
            return (True, r[0],\
                    " ".join([pipes.quote(s) for s in r[1:]]))
        return (True, r, None)

    # Pass-thru for arbitrary, unquoted strings without prompting.

    def string_or_not(self, args):
        return (True, args, None)

    def named_key(self, args):
        return self.input_key(args, lambda : self.callbacks["input"]("key: "))

    def bind(self, key, cmd):
        opt = self.get_opt_name()
        key = self.translate_key(key)
        c = self.callbacks["get_conf"]()
        if not cmd:
            if key in c[opt]["key"]:
                log.info("[%s] %s = %s" % (opt, key, c[opt]["key"][key]))
                return True
            else:
                return False
        else:
            log.info("Binding %s.%s to %s" % (opt, key, cmd))

            c[opt]["key"][key] = cmd
            self.callbacks["set_conf"](c)
            return True
