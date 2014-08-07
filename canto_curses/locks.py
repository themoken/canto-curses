# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2014 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.rwlock import RWLock

config_lock = RWLock('config_lock')
var_lock = RWLock('var_lock')

# This lock can be held with write to keep sync operations from happening.
sync_lock = RWLock("global sync lock")
