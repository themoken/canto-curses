# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2016 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import PluginHandler, Plugin

from .tagcore import tag_updater

import traceback
import logging
import curses
import shlex
import pipes

import readline

log = logging.getLogger("COMMAND")

cmds = {}
arg_types = {}
aliases = {}

# These objects don't really need to be objects, but they're cleaner than
# tossing around a zillion tuples.

class CantoCommand(object):
    def __init__(self, obj, name, func, args, help_txt, group):
        self.name = name
        self.obj = obj              # 0
        self.func = func            # 1
        self.args = args            # 2
        self.help_txt = help_txt    # 3
        self.group = group          # 4

class CantoArgType():
    def __init__(self, obj, name, help_txt, validator, hook):
        self.name = name
        self.obj = obj                  # 0
        self.help_txt = help_txt        # 1
        self.validator = validator      # 2
        self.hook = hook                # 3

class CantoAlias():
    def __init__(self, obj, alias, longform):
        self.alias = alias
        self.obj = obj              # 0
        self.longform = longform    # 1

def register_command(obj, name, func, args, help_txt, group="hidden"):
    c = CantoCommand(obj, name, func, args, help_txt, group)
    if name not in cmds:
        cmds[name] = [ c ]
    else:
        cmds[name].append(c)

def register_commands(obj, cmds, group="hidden"):
    for name in cmds:
        func, args, help_text = cmds[name]
        register_command(obj, name, func, args, help_text, group)

def commands(g=None):
    c = []

    for ck in cmds.keys():
        group = cmds[ck][-1].group
        if group == "hidden":
            continue
        if g and g != group:
            continue

        for ak in aliases.keys():
            if aliases[ak][-1].longform == ck:
                c.append(ak)
                break
        else:
                c.append(ck)
    return c

def groups():
    g = []
    for ck in cmds.keys():
        grp = cmds[ck][-1].group
        if grp != "hidden" and grp not in g:
            g.append(grp)
    return g

def command_help(command, detailed=False):
    lookup = shlex.split(command)
    working_cmd = _get_max_sig(lookup)[-1]

    if not detailed:
        s = "%s" % working_cmd.help_txt
        if '\n' in s:
            s = s[:s.index('\n')]
    else:
        s = "%s %s\n" % (command, " ".join(["[" + x + "]" for x in working_cmd.args]))
        s += "\n%s" % working_cmd.help_txt
        for arg in working_cmd.args:
            s += "\n\n"
            s += arg_types[arg][-1].help_txt
    return s

def register_arg_type(obj, name, help_txt, validator, hook=None):
    at = CantoArgType(obj, name, help_txt, validator, hook)
    if name not in arg_types:
        arg_types[name] = [ at ]
    else:
        arg_types[name].append(at)

def register_arg_types(obj, types):
    for name in types:
        register_arg_type(obj, name, *types[name])

def register_alias(obj, alias, longform):
    a = CantoAlias(obj, alias, longform)
    if alias in aliases:
        aliases[alias].append(a)
    else:
        aliases[alias] = [ a ]

def register_aliases(obj, given):
    for alias in given:
        register_alias(obj, alias, given[alias])

# Passthru for any string, including empty
def _string():
    return (None, lambda x : (True, x))

def word():
    def word_validator(x):
        for c in ' \t':
            if c in x:
                return (False, x)
        return (True, x)
    return (None, word_validator)

register_arg_type(_string, "string", "[string] Any string", _string)
register_arg_type(word, "word", "[word] Any word (no whitespace)", word)

# Unregister, clear out obj associations, del keys if empty.

def _unregister(obj, dct, name):
    if name in dct:
        dct[name] = [ x for x in dct[name] if x.obj != obj]
        if not dct[name]:
            del dct[name]

def unregister_command(obj, name):
    _unregister(obj, cmds, name)

def unregister_arg_type(obj, typ):
    _unregister(obj, arg_types, typ)

def unregister_alias(obj, alias):
    _unregister(obj, aliases, alias)

def unregister_all(obj):
    for key in list(cmds.keys()):
        unregister_command(obj, key)
    for key in list(arg_types.keys()):
        unregister_arg_type(obj, key)
    for key in list(aliases.keys()):
        unregister_alias(obj, key)

# Take a split lookup and unalias the first argument

def _unalias(lookup):
    longest_alias = ""

    # Re-combine to match across multiple tokens
    total = " ".join([ shlex.quote(x) for x in lookup])

    # Commands are automatically aliases of themselves, so that, for example
    # "quit" won't be expanded into "quituit"

    possibles = list(aliases.keys())
    possibles.extend(cmds.keys())

    # Expand an alias into the lookup
    for alias in possibles:
        if not total.startswith(alias):
            continue
        if len(alias) > len(longest_alias):
            longest_alias = alias

    if longest_alias == "" or longest_alias in cmds:
        return lookup

    # deref -1 for latest register, 1 for longform instead of obj
    total = total.replace(longest_alias, aliases[longest_alias][-1].longform, 1)

    log.debug("Unaliased to: %s", total)

    return shlex.split(total)

# Use lookup information to find longest possible sig So, given
# ['remote','addfeed'], return the signature for "remote addfeed" instead of
# just "remote". This lets us get completions for specific subcommands.

# Returns the a tuple with sig info, and a match, which has the command
# stripped out.

def _get_max_sig(lookup):
    lookup = _unalias(lookup)
    match = []
    ret = None

    for i in range(len(lookup)):
        test = " ".join(lookup[0:i + 1])

        if test in cmds:
            ret = cmds[test][-1]
            match = lookup[i + 1:]
        else:
            break

    return match, ret

def cmd_complete_info():
    buf = readline.get_line_buffer()

    lookup = shlex.split(buf)

    # If there's a space, we've moved on to a new argument, so stub in an empty
    # partial argument.

    if not buf or buf[-1] == ' ':
        lookup.append('')
        prefix = ''
    else:
        prefix = lookup[-1]

    if len(lookup) == 1:
        c = list(cmds.keys())
        c.extend(list(aliases.keys()))
        c.sort()
        log.debug("CMDS: %s", c)
        return ("", "", c)
    else:
        lookup, sig = _get_max_sig(lookup)

        # No matches, bail
        if not sig:
            return None

        # No completing beyond end of arguments

        if len(lookup) > len(sig.args):
            log.debug("completing too many args")
            return None

        # XXX these should check that type exists for plugins

        # validate that the arguments we're not completing are okay
        # so that we don't tab complete a broken command.

        for i, typ in enumerate(sig.args[:len(lookup) - 1]):
            completions, validator = arg_types[typ][-1].validator()
            if not validator(lookup[i]):
                return None

        # now get completions for the actual terminating command

        at = arg_types[sig.args[len(lookup) - 1]][-1]
        if at.hook:
            at.hook()
        completions, validator = at.validator()
        return (sig.help_txt, at.help_txt, completions)
    return None

def cmd_execute(cmd):
    lookup = shlex.split(cmd)

    if not lookup:
        return False

    lookup, sig = _get_max_sig(lookup)

    if not sig:
        return False

    args = []

    for i, typ in enumerate(sig.args):
        completions, validator = arg_types[typ][-1].validator()

        # If we're on the last part of the sig, and there's more than one
        # argument remaining, then smash them together in such a way that
        # shlex.split will properly reparse them.

        if i == len(sig.args) - 1 and len(lookup) > (i + 1):
            token = " ".join([ shlex.quote(x) for x in lookup[i:]])
        elif i < len(lookup):
            token = lookup[i]
        else:
            token = ""

        okay, r = validator(token)

        if not okay:
            log.info("'%s' is not a valid %s" % (token, typ))
            return False
        args.append(r)

    sig.func(*args)
    return True

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

def _int_check(x):
    try:
        r = int(x)
        return (True, r)
    except:
        return (False, None)

def _int_range(name, itrs, syms, fallback, s):
    s.strip()

    if (not s):
        if fallback:
            log.debug("falling back to %s", fallback)
            return (True, fallback)
        return (True, [])

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
                if item or ( item == '' and not fallback ):
                    log.warn("Invalid %s : '%s'" % (name, item))

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

        log.debug("trying key: %s", optname)

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

