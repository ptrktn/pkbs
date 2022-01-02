#!/bin/sh

set -x

mylog() {
	local msg=$1
	echo $msg
	logger -n $RSYSLOG_SERVER "$msg"
}

mylog "Hello, World! XX"
