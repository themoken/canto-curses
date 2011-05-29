#!/bin/bash

# This tests pinching the enumerated objects, to make sure
# that they don't expand vertically and prints the ellipsis

canto-daemon -v -D ./ &

cp canto-addfeed.xml /tmp/

function stimulate() {
    sleep 3

    echo -n "e"

    sleep 3
    echo -n ":"
    sleep 0.5
    echo "dump-screen canto-screen"

    echo -n "q"
}

stimulate | canto-curses -v -D ./

canto-remote -D ./ kill

rm /tmp/canto*.xml
