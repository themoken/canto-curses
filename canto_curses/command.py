# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2014 Jack Miller <jack@codezen.org>
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

def register_arg_type(obj, name, help_txt, validator, hook=None):
    if name not in arg_types:
        arg_types[name] = [(obj, help_txt, validator, hook)]
    else:
        arg_types[name].append((obj, help_txt, validator, hook))

def register_arg_types(obj, types):
    for name in types:
        register_arg_type(obj, name, *types[name])

# Passthru for any string, including empty
def _string():
    return (None, lambda x : (True, x))

register_arg_type(_string, "string", "Any String", _string)

def unregister_command(obj, name):
    cmds[name] = [ x for x in cmds[name] if x[0] != obj ]

def unregister_all(obj):
    for key in cmds.keys():
        cmds[key] = [ x for x in cmds[key] if x[0] != obj ]
    for key in arg_types.keys():
        arg_types[key] = [ x for x in arg_types[key] if x[0] != obj ]

# TODO : Make aliases registerable, for plugins.

aliases = {
    "browser" : "remote one-config CantoCurses.browser.path",
    "txt_browser" : "remote one-config --eval CantoCurses.browser.text",
    "add" : "remote addfeed",
    "del" : "remote delfeed",
    "list" : "remote listfeeds",
    "q" : "quit",
    "filter" : "transform",
    "sort" : "transform",
    "global_transform" : "remote one-config defaults.global_transform",
    "cursor_type" : "remote one-config CantoCurses.taglist.cursor.type",
    "cursor_scroll" : "remote one-config CantoCurses.taglist.cursor.scroll",
    "cursor_edge" : "remote one-config --eval CantoCurses.taglist.cursor.edge",
    "story_unselected" : "remote one-config CantoCurses.story.unselected",
    "story_selected" : "remote one-config CantoCurses.story.selected",
    "story_selected_end" : "remote one-config CantoCurses.story.selected_end",
    "story_unselected_end" : "remote one-config CantoCurses.story.unselected_end",
    "story_unread" : "remote one-config CantoCurses.story.unread",
    "story_read" : "remote one-config CantoCurses.story.read",
    "story_read_end" : "remote one-config CantoCurses.story.read_end",
    "story_unread_end" : "remote one-config CantoCurses.story.unread_end",
    "story_unmarked" : "remote one-config CantoCurses.story.unmarked",
    "story_marked" : "remote one-config CantoCurses.story.marked",
    "story_marked_end" : "remote one-config CantoCurses.story.marked_end",
    "story_unmarked_end" : "remote one-config CantoCurses.story.unmarked_end",
    "tag_unselected" : "remote one-config CantoCurses.tag.unselected",
    "tag_selected" : "remote one-config CantoCurses.tag.selected",
    "tag_selected_end" : "remote one-config CantoCurses.tag.selected_end",
    "tag_unselected_end" : "remote one-config CantoCurses.tag.unselected_end",
    "update_interval" : "remote one-config --eval CantoCurses.update.auto.interval",
    "update_style" : "remote one-config CantoCurses.update.style",
    "update_auto" : "remote one-config --eval CantoCurses.update.auto.enabled",
    "border" : "remote one-config --eval CantoCurses.taglist.border",
    "reader_align" : "remote one-config CantoCurses.reader.window.align",
    "reader_float" : "remote one-config --eval CantoCurses.reader.window.float",
    "keep_time" : "remote one-config --eval defaults.keep_time",
    "keep_unread" : "remote one-config --eval defaults.keep_unread",
    "kill_daemon_on_exit" : "remote one-config --eval CantoCurses.kill_daemon_on_exit"
}

# Take a split lookup and unalias the first argument

def _unalias(lookup):

    # Expand an alias into the lookup
    for alias in aliases:
        if not lookup[0].startswith(alias):
            continue
        log.debug("De-alias: %s" % alias)
        base = shlex.split(aliases[alias])
        if len(lookup[0]) > len(alias):
            base += [ lookup[0][len(alias):] ]
        return base + lookup[1:]
    else:
        return lookup

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
        log.debug("CMDS: %s" % c)
        return ("", "", c)
    else:
        lookup, sig = _get_max_sig(lookup)

        # No matches, bail
        if not sig:
            return None

        c_obj, c_func, c_sig, c_hlp = sig

        # No completing beyond end of arguments

        if len(lookup) > len(c_sig):
            log.debug("completing too many args")
            return None

        # XXX these should check that type exists for plugins

        # validate that the arguments we're not completing are okay
        # so that we don't tab complete a broken command.

        for i, typ in enumerate(c_sig[:len(lookup) - 1]):
            obj, hlp, val, hook = arg_types[typ][-1]
            completions, validator = val()
            if not validator(lookup[i]):
                return None

        # now get completions for the actual terminating command

        obj, hlp, val, hook = arg_types[c_sig[len(lookup) - 1]][-1]
        if hook:
            hook()
        completions, validator = val()
        return (c_hlp, hlp, completions)
    return None

def cmd_complete(prefix, index):
    log.debug("COMPLETE: %s %s" % (prefix, index))
    r = cmd_complete_info()
    if r:
        c_hlp, a_hlp, possibles = r
        if not possibles:
            return None
        possibles = [ x for x in possibles if x.startswith(prefix) ]
        if index < len(possibles):
            return possibles[index]

def cmd_execute(cmd):
    lookup = shlex.split(cmd)

    if not lookup:
        return False

    lookup, sig = _get_max_sig(lookup)

    if not sig:
        return False

    c_obj, c_func, c_sig, c_hlp = sig
    args = []

    for i, typ in enumerate(c_sig):
        obj, hlp, val, hook = arg_types[typ][-1]
        completions, validator = val()

        # If we're on the last part of the sig, and there's more than one
        # argument remaining, then smash them together in such a way that
        # shlex.split will properly reparse them.

        if i == len(c_sig) - 1 and len(lookup) > (i + 1):
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

    c_func(*args)
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

    # If our fallback was empty, fail it.
    if not rlist:
        return (False, None)

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

