# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import PluginHandler, Plugin

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

def register_commands(obj, cmds):
    for name in cmds:
        func, args, help_text = cmds[name]
        register_command(obj, name, func, args, help_text)

arg_types = {}

def register_arg_type(obj, name, help_txt, validator):
    if name not in arg_types:
        arg_types[name] = [(obj, help_txt, validator)]
    else:
        arg_types[name].append((obj, help_txt, validator))

def register_arg_types(obj, types):
    for name in types:
        help_txt, validator = types[name]
        register_arg_type(obj, name, help_txt, validator)

def unregister_all(obj):
    for key in cmds.keys():
        cmds[key] = [ x for x in cmds[key] if x[0] != obj ]
    for key in arg_types.keys():
        arg_types[key] = [ x for x in arg_types[key] if x[0] != obj ]

def cmd_complete(prefix, index):
    log.debug("COMPLETE: %s %s" % (prefix, index))
    buf = readline.get_line_buffer()

    lookup = shlex.split(buf)

    # If there's a space, we've moved on to a new argument, so stub in an empty
    # partial argument.

    if not buf or buf[-1] == ' ':
        lookup.append('')
        prefix = ''
    else:
        prefix = lookup[-1]

    log.debug("LOOKUPS: %s" % lookup)
    log.debug("PREFIX: %s" % prefix)

    if len(lookup) == 1:
        c = [ x for x in cmds.keys() if x.startswith(prefix)]
        c.sort()
        log.debug("CMDS: %s" % c)
        if index < len(c):
            return c[index]
    else:
        # Don't complete non-existent commands
        if lookup[0] not in cmds:
            return None

        c_obj, c_func, c_sig, c_hlp = cmds[lookup[0]][-1]

        # Trim the command out of the lookups

        lookup = lookup[1:]

        # No completing beyond end of arguments

        if len(lookup) > len(c_sig):
            log.debug("completing too many args")
            return None

        # XXX these should check that type exists for plugins

        # validate that the arguments we're not completing are okay
        # so that we don't tab complete a broken command.

        for i, typ in enumerate(c_sig[:len(lookup) - 1]):
            log.debug("COMPLETION TYPE: %s" % (typ,))
            obj, hlp, val = arg_types[typ][-1]
            completions, validator = val()
            if not validator(lookup[i]):
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
# itrs - a dict of iterables being indexed (i.e. a lists of items), each key is a domain
# syms - symbolics (i.e. { 'domain' : { '*' : all_items, '.' : [ current_item ]}})
# fallback - list of items to return if no indices
# s - input string to parse

# This is likely used lambda x: _int_range("mytype", {}, {}, x) to encapsulate the rest
# of the state from the command infrastructure

def _range(cur_iter, syms, item):
    cur_syms = syms[cur_iter]

    # Convert into indices
    if item in cur_syms:

        # This will default to the first item if passed a sym with more
        # items (*)

        return cur_syms[item][0]
    else:
        try:
            item = int(item)
            return item
        except:
            pass
    return None

def _int_range(name, itrs, syms, fallback, s):
    slist = s.split(',')

    # Default domain is 'all'
    cur_iter = 'all'

    idxlist = []

    # Convert slist into a list of numeric indices

    for item in slist:
        item.strip()

        # Deal with ranges
        if "-" in item:
            start, stop = item.split('-')

            start_idx = _range(cur_iter, syms, start)
            stop_idx = _range(cur_iter, syms, stop)

            if start_idx == None:
                log.warn("Couldn't convert range start: %s" % start)
                continue
            if start_idx < 0 or start_idx >= len(itrs[cur_iter]):
                log.warn("Range start out of bounds: %s (%s)" % (start_idx, len(itrs[cur_iter])))
                continue
            if stop_idx == None:
                log.warn("Couldn't convert range stop: %s" % stop)
                continue
            if stop_idx < 0 or stop_idx >= len(itrs[cur_iter]):
                log.warn("Range stop out of bounds: %s (%s)" % (stop_idx, len(itrs[cur_iter])))
                continue

            idxlist.extend([ (cur_iter, x) for x in range(start_idx,stop_idx + 1) ])

        # Convert specials... note that domains come before syms, but it would
        # be a bad idea to have conflicts anyway.

        elif item in itrs:
            cur_iter = item
        elif item in syms[cur_iter]:
            idxlist.extend([ (cur_iter, x) for x in syms[cur_iter][item] ])
        else:
            try:
                r = int(item)
                idxlist.append((cur_iter, r))
            except:
                log.warn("Invalid %s : %s" % (name, item))

    # Strip down to unique indices

    uidxlist = []
    for tup in idxlist:
        if tup not in uidxlist:
            uidxlist.append(tup)

    # Convert into list of items in itr

    rlist = []
    for domain, idx in uidxlist:
        if 0 <= idx < len(itrs[domain]):
            if itrs[domain][idx] not in rlist:
                rlist.append(itrs[domain][idx])
        else:
            log.warn("%s out of range of %s domain: %s idx with len %s" % (name, domain, idx, len(itrs[domain])))

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
