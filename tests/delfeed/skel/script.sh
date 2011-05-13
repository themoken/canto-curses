#!/bin/bash

# This tests the remote: capability as well as the ability to show
# freshly added feeds immediately.

canto-daemon -v -D ./ &

function stimulate() {
    sleep 3

    echo -n ":"
    sleep 0.5
    echo "remote delfeed file:///tmp/canto.xml"
    sleep 0.5
    echo -n " "

    sleep 2
    echo -n ":"
    sleep 0.5
    echo "dump-screen canto-screen"

    echo -n "q"
}

stimulate | canto-curses -v -D ./

canto-remote -D ./ kill
