#!/bin/sh

PARAM_FILE=./ersimu/examples/szalai-chd-ferroin-revival.txt

preflight() {
	apk add --no-cache build-base gnuplot git
	git clone https://github.com/ptrktn/ersimu.git
}

run() {
	chmod u+x ersimu/ersimu.py
	cp $PARAM_FILE ./input.txt
	time ./ersimu/ersimu.py --verbose --run --plot H2Q input.txt 2>&1
	ls -lh
}

postflight() {
	rm -fr ersimu *.dat simulation
}

preflight
run
postflight

exit 0
