#Testing goto hooks, ewancoder, 2014.
#Using these hooks you can make your own RSS feed based on the links you read.
#This (test) plugin writes opened links to the files:
#   ~/goto.txt
#   ~/reader_goto.txt
#   ~/taglist_goto.txt
#   ~/fetch.txt
#   ~/reader_fetch.txt

from canto_next.hooks import on_hook

import os
import shlex

#Works every time link is opened, because even fetch() uses goto()
def goto(goto, links):
    for link in links:
        os.system("echo %s >> ~/goto.txt" % shlex.quote(link))

#Works when a link is opened from the reader
def reader_goto(cmdgoto, links):
    for link in links:
        os.system("echo %s >> ~/reader_goto.txt" % shlex.quote(link))

#Works when a link opened from taglist (main canto-curses screen)
def taglist_goto(taglistgoto, items):
    for item in items:
        os.system("echo %s >> ~/taglist_goto.txt" % shlex.quote(item.content['link']))

#Works when a link is fetched
def fetch(fetch, links):
    for link in links:
        os.system("echo %s >> ~/fetch.txt" % shlex.quote(link))

#Works when a link is fetched from the reader
def reader_fetch(cmdfetch, links):
    for link in links:
        os.system("echo %s >> ~/reader_fetch.txt" % shlex.quote(link))

#Corresponding hooks
on_hook("goto_trigger", goto)
on_hook("reader_goto_trigger", reader_goto)
on_hook("taglist_goto_trigger", taglist_goto)
on_hook("fetch_trigger", fetch)
on_hook("reader_fetch_trigger", reader_fetch)
