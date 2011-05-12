#!/bin/bash

# This tests the remote: capability as well as the ability to show
# freshly added feeds immediately.

canto-daemon -v -D ./ &

cp canto-addfeed.xml /tmp/

function stimulate() {
    sleep 3

    echo -n ":"
    sleep 0.5
    echo "remote addfeed file:///tmp/canto-addfeed.xml"
    sleep 0.5
    echo -n " "

    sleep 0.5
    echo -n "\\"
    sleep 3;

    echo -n ":"
    sleep 0.5
    echo "dump-screen canto-screen"

    echo -n "q"
}

stimulate | canto-curses -v -D ./

canto-remote -D ./ kill

rm /tmp/canto*.xml
