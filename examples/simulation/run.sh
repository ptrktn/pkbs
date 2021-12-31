#!/bin/sh

PARAM_FILE=./ersimu/examples/szalai-chd-ferroin-revival.txt

preflight() {
	apk add --no-cache build-base gnuplot git
	git clone https://github.com/ptrktn/ersimu.git
}

run() {
	./ersimu/ersimu.py --name revival --verbose --run --plot all ${PARAM_FILE}
}

postflight() {
	rm -fr ersimu simulation.dat simulation
}

preflight
run
postflight

exit 0
