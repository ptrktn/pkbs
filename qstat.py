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
import sys
import os
import time
from datetime import timedelta
import asyncio
import nats
from nats.errors import TimeoutError
import json


async def kvx(queue, jobid, x, get=True):
    nc = await nats.connect("nats://127.0.0.1:14222")
    js = nc.jetstream()

    # Create a KV
    kv = await js.create_key_value(bucket='MY_KV')
    await js.add_stream(name="mystream")

    if get:
        res = await kv.get(f'{jobid}@{queue}')
        # Set and retrieve a value
    else:
        res = await kv.put(f'{jobid}@{queue}', x.encode())
    await nc.close()
    return res


def mylog(message):
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())} {message}")
    sys.stdout.flush()
    if cfg["syslog"]:
        os.system(f"logger '{message}'")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--creds', default="")
    parser.add_argument('-q', '--queue', default="jobs")
    parser.add_argument('-s', '--servers', default="nats")
    parser.add_argument("--syslog", action="store_true", dest="syslog", default=False)
    parser.add_argument('--token', default="")
    parser.add_argument('-v', '--verbose', action="store_true", default=False)
    args, unknown = parser.parse_known_args()

    if args.syslog:
        cfg["syslog"] = True

    async def error_cb(e):
        # mylog("Error:", e)
        pass

    async def reconnected_cb():
        mylog(f"Connected to NATS at {nc.connected_url.netloc}...")

    options = {
        "error_cb": error_cb,
        "reconnected_cb": reconnected_cb
    }

    if len(args.creds) > 0:
        options["user_credentials"] = args.creds

    if args.token.strip() != "":
        options["token"] = args.token.strip()

    try:
        if len(args.servers) > 0:
            options['servers'] = args.servers

        nc = await nats.connect(**options)
        jsm = nc.jsm()
    except Exception as e:
        mylog(e)
        sys.exit(1)

    consumer = f"workers"
    sname = f"{args.queue}-stream"
    
    # Create JetStream context.
    js = nc.jetstream()

    # Persist messages on jobs' queue (i.e, subject in Jetstream).
    await js.add_stream(name=sname, subjects=[args.queue])
    s = await jsm.stream_info(sname)
    c = await jsm.consumer_info(sname, consumer)
    if args.verbose:
        print(s)
        print(c)
    print(f"{s.config.name} messages {s.state.messages} pending {c.num_pending}")

    # Replay messages in queue
    await js.add_stream(name=sname, subjects=[args.queue])

    cinfo = await js.add_consumer(
        sname,
        durable_name="qstat",
        deliver_policy=nats.js.api.DeliverPolicy.all,
        filter_subject=args.queue
    )

    jobs = []
    sub = await js.subscribe(args.queue, stream=sname)
    while True:
        try:
            msg = await sub.next_msg()
            jobid = msg.headers["jobid"]
            jobs.append(jobid)
        except nats.errors.TimeoutError:
            # Reached apparent end of stream
            break
        except Exception as e:
            print(e)

    kv = await js.create_key_value(bucket="qstat")
    for jobid in jobs:
        v = await kv.get(f"{jobid}@{args.queue}")
        ji = json.loads(v.value.decode("utf-8"))
        if args.verbose:
            print(json.dumps(ji, indent=4))
        else:
            out = []
            out.append(f"{jobid[:11]:<11}")
            out.append(f"{ji['name'][:22]:<22}")

            if not(ji["node"]):
                ji["node"] = "N/A"
            out.append(f"{ji['node'][:18]:<18}")

            out.append(f"{ji['status'][:10]:<10}")

            if ji["wallclock"]:
                out.append(f"{str(timedelta(seconds=int(ji['wallclock']))):<11}")
            elif ji["started"]:
                out.append(f"{str(timedelta(seconds=int(time.time() - ji['started']))):<11}")
            else:
                x = "--:--:--"
                out.append(f"{x:<11}")

            if None == ji["exit_code"]:
                ji["exit_code"] = "N/A"
            out.append(f"{ji['exit_code']:<3}")

            print(" ".join(out))

    await nc.close()


if __name__ == '__main__':
    asyncio.run(main())
