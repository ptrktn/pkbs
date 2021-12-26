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
import asyncio
import nats
import magic
from nats.errors import TimeoutError
from zipfile import ZIP_DEFLATED, ZipFile
from pathlib import Path
from typing import Union

cfg = {
    "syslog": False
}


# https://stackoverflow.com/a/43141399 
def zip_dir(zip_name: str, source_dir: Union[str, os.PathLike]):
    src_path = Path(source_dir).expanduser().resolve(strict=True)
    # compresslevel=9 ???
    with ZipFile(zip_name, 'w', ZIP_DEFLATED) as zf:
        for file in src_path.rglob('*'):
            zf.write(file, file.relative_to(src_path.parent))


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
    args, unknown = parser.parse_known_args()

    if args.syslog:
        # FIXME import netsyslog?
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
    except Exception as e:
        mylog(e)
        sys.exit(1)

    consumer = f"workers"
    sname = f"{args.queue}-stream"
    
    # Create JetStream context.
    js = nc.jetstream()

    # Persist messages on jobs' queue (i.e, subject in Jetstream).
    await js.add_stream(name=sname, subjects=[args.queue])

    # Create deliver group that will be have load balanced messages.
    #async
    def qsub(msg):
        mylog(f"QSUB {msg.subject} {msg.headers} LEN {len(msg.data)}")
        jobid = msg.headers["jobid"]
        name = msg.headers["name"]
        filename = msg.headers.get("filename")
        
        if filename:
            # FIXME clean sandbox
            sandbox = os.path.join("/var", "tmp", "pkebs", jobid)
            ofile = "stdout.log"
            efile = "stderr.log"
            os.makedirs(sandbox)
            fname = os.path.join(sandbox, filename)
            with open(fname, "wb") as fp:
                fp.write(msg.data)
            ftype = magic.from_file(fname, mime=True)
            mylog(f"Payload '{ftype}' cached to {fname}")
            if "text/x-sh" == ftype:
                command = f"cd {sandbox} && /bin/sh {filename} > {ofile} 2> {efile}"
            elif "application/zip" == ftype:
                with ZipFile(fname, "r") as z:
                    z.extractall(sandbox)
                os.unlink(fname)
                runfile = "run.sh"
                script = os.path.join(sandbox, runfile)
                if not(os.path.isfile(script)):
                    mylog(f"Error: file {runfile} is not found")
                    return
                command = f"cd {sandbox} && /bin/sh {runfile} > {ofile} 2> {efile}"
            else:
                mylog(f"Error: payload file type {ftype} is unsupported")
                return
        else:
            command = msg.data.decode("utf-8")

        mylog(f"Job {jobid} command is: {command}")
        t1 = time.time()
        status = os.system(command)
        t2 = time.time()
        mylog(f"Job {jobid} exited with status {status} and the elapsed wallclock time was {round(t2 - t1, 2)} seconds")

        if filename:
            fname = os.path.join(os.path.dirname(sandbox), f"{jobid}.zip")
            zip_dir(fname, sandbox)
            # FIXME transfer to storage
            # FIXME cleanup

        
    # Create pull based consumer
    sub = await js.pull_subscribe(args.queue, consumer, stream=sname)

    while True:
        try:
            msgs = await sub.fetch(1, 10)
        except nats.errors.TimeoutError:
            # loop over and fetch again
            continue
        except Exception as e:
            mylog(str(e))
            continue
        for msg in msgs:
            await msg.ack()
            info = await js.consumer_info(sname, consumer)
            mylog(f"There are {info.num_pending} pending request(s)")
            # mylog(info)
            qsub(msg)
        

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    try:
        loop.run_forever()
    finally:
        loop.close()
