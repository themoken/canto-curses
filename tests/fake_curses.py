# -*- coding: utf-8 -*-

from canto_curses.widecurse import wcwidth
import sys

self = sys.modules[__name__]
real_curses = __import__("curses")
ascii = __import__("curses.ascii")

# Grab all of constants out

for attr in dir(real_curses):
    if attr[0].isupper():
        setattr(self, attr, getattr(real_curses, attr))

COLOR_PAIRS = 256
SCREEN_HEIGHT = 25
SCREEN_WIDTH = 80

class CursesScreen():
    def getmaxyx(self):
        return (SCREEN_HEIGHT, SCREEN_WIDTH)

    def refresh(self):
        pass

def initscr():
    return CursesScreen()

class CursesPad():
    def __init__(self, height, width):
        self.height = height
        self.width = width

        self.pad = []
        _wide = [ { "attrs" : 0, "char" : " " } ] * width

        for i in range(self.height):
            self.pad.append(_wide[:])

        self.attrs = 0

        self.x = 0
        self.y = 0

    def get_wch(self):
        while True:
            pass

    def keypad(self, arg):
        pass

    def nodelay(self, arg):
        pass

    def attron(self, attr):
        self.attrs |= attr

    def attroff(self, attr):
        self.attrs ^= attr

    def clrtoeol(self):
        y = self.y
        while y == self.y:
            self.waddch(" ")

    def waddch(self, ch):
        if type(ch) == bytes:
            val = { "char" : ch.decode("UTF-8"), "attrs" : self.attrs }
            self.pad[self.y][self.x] = val
            self.x += wcwidth(ch)
        else:
            val = { "char" : ch, "attrs" : self.attrs }
            self.pad[self.y][self.x] = val
            self.x += wcwidth(ch.encode("UTF-8"))

        if self.x >= self.width:
            self.y += 1
            self.x -= self.width

    def overwrite(self, dest_pad, sminrow, smincol, dminrow, dmincol, dmaxrow, dmaxcol):
        rows = (dmaxrow - dminrow) + 1
        cols = (dmaxcol - dmincol) + 1

        for i in range(rows):
            for j in range(cols):
                dest_pad.pad[dminrow + i][dmincol + j] = self.pad[sminrow + i][smincol + j]

    def getyx(self):
        return (self.y, self.x)

    def getmaxyx(self):
        return (self.height, self.width)

    def addstr(self, string):
        print("addstr")
        for c in string:
            self.waddch(c)

    def noutrefresh(self, a, b, c, d, e, f):
        self.dump()

    def erase(self):
        for i in range(self.height):
            for j in range(self.width):
                self.pad[i][j] = { "char" : " ", "attrs" : self.attrs }

    def move(self, y, x):
        self.y = y
        self.x = x

    def dump(self):
        for i in range(self.height):
            print("%02d %s-" % (i, "".join([x["char"] for x in self.pad[i]])))

def newpad(y, x):
    return CursesPad(y, x)

def_pair = [ 1, 0 ]

pairs = []
for i in range(256):
    pairs.append(def_pair[:])

def init_pair(pair, fg, bg):
    pairs[pair][0] = fg
    pairs[pair][1] = bg

def color_pair(pair):
    return pair << 8

def doupdate():
    pass

def raw():
    pass

def cbreak():
    pass

def noecho():
    pass

def start_color():
    pass

def use_default_colors():
    pass

def typeahead(fd):
    pass

def halfdelay(delay):
    pass
