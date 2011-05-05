#!/bin/bash

canto-daemon -v -D ./ &

(sleep 3; echo -n ":"; sleep 0.5; echo "dump-screen canto-screen"; echo -n "q") | canto-curses -v -D ./

canto-remote -D ./ kill
