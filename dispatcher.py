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
import nanoid
from nats.errors import TimeoutError
import json


def mylog(message):
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())} {message}")
    sys.stdout.flush()


async def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--creds', default="")
    parser.add_argument('-c', '--command', default="")
    parser.add_argument('-N', '--name', default="qsub")
    parser.add_argument('-p', '--path', default=os.getenv("WEBDAV_PATH", "pkbs"))
    parser.add_argument('-P', '--path-fixed', default=None)
    parser.add_argument('-q', '--queue', default="jobs")
    parser.add_argument('-s', '--servers', default=os.getenv("NATS_SERVER", "nats-svc"))
    parser.add_argument('-u', '--upload', default=os.getenv("WEBDAV_UPLOAD", "zip"), help="one of files, zip or none")
    parser.add_argument('--token', default="")
    parser.add_argument("file", metavar="FILE", type=str, nargs='?')
    args, unknown = parser.parse_known_args()

    async def error_cb(e):
        mylog(f"Error: {e}")

    async def reconnected_cb():
        mylog(f"Connected to NATS at {nc.connected_url.netloc}...")

    def newjobid():
        custom = (
            "1234567890"
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        )
        return nanoid.generate(custom, 11)

    jobid = f"{newjobid()}"

    options = {
        "error_cb": error_cb,
        "reconnected_cb": reconnected_cb
    }

    headers = {
        "jobid": jobid,
        "name": args.name,
        "path": args.path,
        "upload": args.upload.lower()
    }

    if args.file:
        if os.path.isfile(args.file):
            with open(args.file, "rb") as fp:
                data = fp.read()
            headers["filename"] = os.path.basename(args.file)
            headers["command"] = args.command
        else:
            mylog(f"Error: file {args.file} not found.")
            sys.exit(1)
    elif len(args.command):
        data = args.command.encode()
    else:
        # FIXME
        sys.exit(1)

    if args.path_fixed:
        headers["path-fixed"] = args.path_fixed

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

    # Record the job in key-value store
    kv = await js.create_key_value(bucket="qstat")
    doc = {
        "queued": time.time(),
        "started": None,
        "finished": None,
        "name": args.name,
        "status": "queued",
        "node": None,
        "exit_code": None,
        "wallclock": None
    }
    await kv.put(f'{jobid}@{args.queue}', json.dumps(doc).encode('utf-8'))

    # Publish message to the jobs queue (i.e, subject in Jetstream)
    await js.add_stream(name=f"{args.queue}-stream", subjects=[args.queue])
    ack = await js.publish(args.queue, data, headers=headers)

    await nc.close()

    print(jobid)
    sys.stdout.flush()


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1:]))
