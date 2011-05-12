#!/bin/bash

# This test merely dumps the initial interface under
# a known set of conditions. This will only catch the
# most basic errors.

canto-daemon -v -D ./ &

function stimulate() {
    sleep 3;

    echo -n ":"
    sleep 0.5
    echo "dump-screen canto-screen"

    echo -n "q"
}

stimulate | canto-curses -v -D ./

canto-remote -D ./ kill
