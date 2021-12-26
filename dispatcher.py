#!/usr/bin/env python3

# Source: napts.py/examples/jetstream.py

# Copyright 2016-2019 The NATS Authors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import argparse
import os
import sys
import time
import asyncio
import nats
import uuid
from nats.errors import TimeoutError


def mylog(message):
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())} {message}")
    sys.stdout.flush()


async def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--creds', default="")
    parser.add_argument('-c', '--command', default="")
    parser.add_argument('-N', '--name', default="")
    parser.add_argument('-q', '--queue', default="jobs")
    parser.add_argument('-s', '--servers', default="nats")
    parser.add_argument('--token', default="")
    parser.add_argument("file", metavar="FILE", type=str, nargs='?')
    args, unknown = parser.parse_known_args()

    async def error_cb(e):
        mylog(f"Error: {e}")

    async def reconnected_cb():
        mylog(f"Connected to NATS at {nc.connected_url.netloc}...")

    jobid = str(uuid.uuid4())

    options = {
        "error_cb": error_cb,
        "reconnected_cb": reconnected_cb
    }

    headers = {
        "jobid": jobid,
        "name": args.name,
    }

    if args.file:
        if os.path.isfile(args.file):
            with open(args.file, "rb") as fp:
                data = fp.read()
            # data = str(len(data)).encode()
            headers["filename"] = os.path.basename(args.file)
        else:
            mylog(f"Error: file {args.file} not found.")
            sys.exit(1)
    elif len(args.command):
        data = args.command.encode()
    else:
        # FIXME
        sys.exit(1)
        data = "empty message"
            
    if len(args.creds) > 0:
        options["user_credentials"] = args.creds

    if args.token.strip() != "":
        options["token"] = args.token.strip()

    try:
        if len(args.servers) > 0:
            options['servers'] = args.servers

        nc = await nats.connect(**options)
    except Exception as e:
        mylog(e)
        sys.exit(1)
        
    # Create JetStream context.
    js = nc.jetstream()

    # Persist messages on jobs' queue (i.e, subject in Jetstream).
    await js.add_stream(name=f"{args.queue}-stream", subjects=[args.queue])
    ack = await js.publish(args.queue, data, headers=headers)
    # mylog(ack)
    mylog(f"Job {jobid} has been dispatched")
    await nc.close()


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1:]))
