#!/bin/bash

for test_dir in "$@"; do
    # Eliminate old cruft
    rm -f $test_dir/*

    # Copy in skel
    cp $test_dir/skel/* $test_dir/

    # Run test script with given size.

    cd $test_dir
    xterm -title "canto-test" -geometry 80x50 -e ./script.sh
    cd ..

    # Compare outputs
    hexdump $test_dir/canto-screen > $test_dir/output

    gunzip -c $test_dir/expected.gz | hexdump > $test_dir/expected

    TESTDIFF=`diff -u ./$test_dir/output ./$test_dir/expected`
    if [ -n "$TESTDIFF" ]; then
        echo "TEST $test_dir FAILED"
        diff -u ./$test_dir/output ./$test_dir/expected
    else
        echo "TEST $test_dir OK"
    fi
done
