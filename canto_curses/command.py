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

import readline

log = logging.getLogger("COMMAND")

cmds = {}

def register_command(obj, name, func, args, help_txt):
    if name not in cmds:
        cmds[name] = [(obj, func, args, help_txt)]
    else:
        cmds[name].append((obj, func, args, help_txt))

arg_types = {}

def register_arg_type(obj, name, help_txt, validator):
    if name not in arg_types:
        arg_types[name] = [(obj, help_txt, validator)]
    else:
        arg_types[name].append((obj, help_txt, validator))

def unregister_all(obj):
    for key in cmds.keys():
        cmds[key] = [ x for x in cmds[key] if x[0] != obj ]
    for key in arg_types.keys():
        arg_types[key] = [ x for x in arg_types[key] if x[0] != obj ]

def cmd_complete(prefix, index):
    log.debug("COMPLETE: %s %s" % (prefix, index))
    lookup = readline.get_line_buffer()[0:readline.get_begidx()]
    lookup = shlex.split(lookup)

    log.debug("LOOKUPS: %s" % lookup)

    if len(lookup) == 0:
        c = [ x for x in cmds.keys() if x.startswith(prefix)]
        c.sort()
        log.debug("CMDS: %s" % c)
        if index < len(c):
            return c[index]
    else:
        if lookup[0] not in cmds:
            return None
        c_obj, c_func, c_sig, c_hlp = cmds[lookup[0]][-1]

        # No completing beyond end of arguments
        if (len(lookup) - 1) > len(c_sig):
            return None

        # XXX these should check that type exists for plugins

        # validate that the arguments we're not completing are okay
        # so that we don't tab complete a broken command.

        for i, typ in enumerate(c_sig[:len(lookup) - 1]):
            obj, hlp, val = arg_types[typ]
            completions, validator = val()
            if not validator(lookup[i + 1]):
                return None

        # now get completions for the actual terminating command

        obj, hlp, val = arg_types[c_sig[len(lookup) - 1]][-1]
        log.debug("%s %s %s" % (obj, hlp, val))
        completions, validator = val()
        if completions:
            possibles = [ x for x in completions if x.startswith(prefix)]
            if index < len(possibles):
                return possibles[index]
    return None

def cmd_execute(cmd):
    lookup = shlex.split(cmd)
    if not lookup or lookup[0] not in cmds:
        return False

    c_obj, c_func, c_sig, c_hlp = cmds[lookup[0]][-1]
    args = []

    for i, typ in enumerate(c_sig):
        obj, hlp, val = arg_types[typ][-1]
        completions, validator = val()

        if i < len(lookup) - 1:
            okay, r = validator(lookup[i + 1])
        else:
            okay, r = validator("")

        if not okay:
            log.info("%s is not a valid %s" % (lookup[i + 1], typ))
            return False
        args.append(r)

    c_func(*args)

# Return a function taking a string definition of a list, with possible special
# characters, and return an explicit list. Each item in the returned list will be unique, so
# doing something like 1,2,* won't repeat items 1 and 2.

# name - type name (for decent error output)
# itr - the iterable that is being indexed (i.e. a list of items)
# syms - symbolics (i.e. { '*' : all_items, '.' : [ current_item ]})
# fallback - list of items to return if no indices
# s - input string to parse

# This is likely used lambda x: _int_range("mytype", [], {}, x) to encapsulate the rest
# of the state from the command infrastructure

def _int_range(name, itr, syms, fallback, s):
    slist = s.split(',')

    idxlist = []

    # Convert slist into a list of numeric indices

    for item in slist:
        item.strip()

        # Convert
        if item in syms:
            idxlist.extend(syms[item])
        else:
            try:
                r = int(item)
                idxlist.append(r)
            except:
                log.warn("Invalid %s : %s" % (name, item))

    # Strip down to unique indices

    uidxlist = []
    for idx in idxlist:
        if idx not in uidxlist:
            uidxlist.append(idx)

    # Convert into list of items in itr

    rlist = []
    for idx in uidxlist:
        if 0 <= idx < len(itr):
            if itr[idx] not in rlist:
                rlist.append(itr[idx])
        else:
            log.warn("%s out of range: %s with len %s" % (name, idx, len(itr)))

    if not rlist:
        rlist = fallback
        log.debug("%s falling back to %s" % (rlist, fallback))

    # XXX should we return (False, []) on rlist empty, or...?

    return (True, rlist)

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
