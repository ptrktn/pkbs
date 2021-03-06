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
import hashlib
import requests
import json
import nanoid
from shutil import rmtree
import logging
from logging.handlers import SysLogHandler
import socket
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from uwebdavclient.client import Client


cfg = {
    "logger": None
}


class ContextFilter(logging.Filter):
    hostname = socket.gethostname()

    def filter(self, record):
        record.hostname = ContextFilter.hostname
        return True


def mylog(message, stdout=True):
    if stdout:
        print(f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())} {message}")
        sys.stdout.flush()
    if cfg["logger"]:
        cfg["logger"].info(message)


# https://stackoverflow.com/a/43141399
def zip_dir(zip_name: str, source_dir: Union[str, os.PathLike]):
    src_path = Path(source_dir).expanduser().resolve(strict=True)
    # compresslevel=9 ???
    with ZipFile(zip_name, 'w', ZIP_DEFLATED) as zf:
        for file in src_path.rglob('*'):
            zf.write(file, file.relative_to(src_path.parent))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--creds', default="")
    parser.add_argument('--max-jobs', default=None)
    parser.add_argument('-q', '--queue', default="jobs")
    parser.add_argument(
        '-s',
        '--servers',
        default=os.getenv(
            "NATS_SERVER",
            "nats-svc"))
    parser.add_argument(
        "--syslog",
        action="store_true",
        dest="syslog",
        default=False)
    parser.add_argument('--token', default="")
    args, unknown = parser.parse_known_args()

    if args.syslog:
        try:
            address = (
                os.getenv(
                    "RSYSLOG_SERVER",
                    "rsyslog-svc.pkbs-system"),
                514)
            syslog = SysLogHandler(address=address)
            syslog.addFilter(ContextFilter())
            fmt = "%(asctime)s %(hostname)s %(message)s"
            formatter = logging.Formatter(fmt, datefmt='%b %d %H:%M:%S')
            syslog.setFormatter(formatter)
            logger = logging.getLogger()
            logger.addHandler(syslog)
            logger.setLevel(logging.INFO)
            cfg["logger"] = logger
        except Exception as e:
            # Keep calm and carry on without syslog
            pass

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

    consumer = "workers"
    sname = f"{args.queue}-stream"

    # Create JetStream context
    js = nc.jetstream()

    # Persist messages on jobs' queue (i.e, subject in Jetstream).
    await js.add_stream(name=sname, subjects=[args.queue])
    kv = await js.create_key_value(bucket="qstat")

    async def jobinfo(jobid, doc=None):
        if doc:
            await kv.put(f'{jobid}@{args.queue}', json.dumps(doc).encode("utf-8"))
        else:
            v = await kv.get(f"{jobid}@{args.queue}")
            return json.loads(v.value.decode("utf-8"))

    def tempname():
        return os.path.join(
            "/tmp",
            nanoid.generate("1234567890abcdefghijklmnopqrstuvwxyz", 10)
        )

    async def qsub(msg):
        tidy_headers = dict(msg.headers)
        if tidy_headers.get("webdav-password"):
            tidy_headers["webdav-password"] = "*****"
        mylog(f"QSUB {msg.subject} {tidy_headers} LEN {len(msg.data)}")
        jobid = msg.headers["jobid"]
        name = msg.headers.get("name", "")
        filename = msg.headers.get("filename")
        command = msg.headers.get("command")
        fixed_path = msg.headers.get("fixed-path")  # FIXME
        upload = msg.headers.get("upload", os.getenv("WEBDAV_UPLOAD", "files")).lower()
        webdav_hostname = msg.headers.get("webdav-hostname", os.getenv(
            "WEBDAV_HOSTNAME",
            "http://nextcloud-svc.pkbs-system"))
        webdav_root = msg.headers.get("webdav-root", os.getenv(
            "WEBDAV_ROOT",
            "remote.php/dav/files/admin"))
        webdav_path = msg.headers.get("path", os.getenv("WEBDAV_PATH", "pkbs"))
        webdav_user = msg.headers.get("webdav-login",
                                      os.getenv("WEBDAV_LOGIN", "admin"))
        webdav_passwd = msg.headers.get("webdav-password",
                                        os.getenv("WEBDAV_PASSWORD", "admin"))
        webdav_insecure = bool(msg.headers.get("webdav-insecure",
                                               os.getenv("WEBDAV_INSECURE", "0")))

        if not(jobid):
            mylog("Jobs without jobid item in header will not be processed")
            return

        if upload in ["zip", "files"]:
            mylog(f"Upload {upload}")
            webdav_options = {
                'hostname': webdav_hostname,
                'login': webdav_user,
                'password': webdav_passwd,
                'root': webdav_root,
                'insecure': webdav_insecure,
                'verbose': True,
            }
            webdav = Client(webdav_options)

        sandbox = os.path.join("/var", "tmp", "pkbs", jobid)
        tmpdir = tempname()
        nodefile = tempname()

        with open(nodefile, "w") as fp:
            fp.write(f"{os.getenv('HOSTNAME')}\n")

        # FIXME try
        os.makedirs(tmpdir)

        pbsenv = (
            "export"
            " NCPU=1"
            " PBS_ENVIRONMENT=BATCH"
            f" PBS_JOBDIR={sandbox}"
            f" PBS_JOBID={jobid}"
            f" PBS_JOBNAME={name}"
            f" PBS_NODEFILE={nodefile}"
            f" PBS_NODENUM=0"
            f" PBS_QUEUE={args.queue}"
            f" TMPDIR={tmpdir}"
        )

        if filename:
            ofile = "stdout.txt"
            efile = "stderr.txt"
            os.makedirs(sandbox)
            fname = os.path.join(sandbox, filename)
            with open(fname, "wb") as fp:
                fp.write(msg.data)
            ftype = magic.from_file(fname, mime=True)
            mylog(f"Payload '{ftype}' cached to {fname}")
            if ftype in ["text/x-sh", "text/x-shellscript"]:
                command = f"cd {sandbox} && /bin/sh {filename} > {ofile} 2> {efile}"
            elif "application/zip" == ftype:
                with ZipFile(fname, "r") as z:
                    z.extractall(sandbox)
                os.unlink(fname)
                if command:
                    # Python ZipFile rudely trashes executable permissions
                    command = f"cd {sandbox} && chmod u+x {command} && ./{command} > {ofile} 2> {efile}"
                else:
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

        # Update job info: started
        ji = await jobinfo(jobid)
        t1 = time.time()
        ji["started"] = t1
        ji["status"] = "running"
        ji["node"] = os.getenv("HOSTNAME", "UNDEFINED")
        await jobinfo(jobid, ji)

        # Run the job
        status = os.system(f"{pbsenv} && {command}")
        t2 = time.time()
        wallclock = round(t2 - t1, 2)

        # Update job info: finished
        ji["exit_code"] = status >> 8
        ji["finished"] = t2
        ji["status"] = "finished"
        ji["wallclock"] = wallclock
        await jobinfo(jobid, ji)

        mylog(
            f"Job {jobid} exited with status {status} and the elapsed wallclock time was {wallclock} seconds")

        if filename and "zip" == upload:
            zipname = os.path.join(
                os.path.dirname(sandbox),
                f"{name}-{jobid}.zip")
            zip_dir(zipname, sandbox)
            webdav.mkdir(webdav_path)
            status = webdav.upload_sync(webdav_path, zipname)  # FIXME
            # FIXME cleanup zip
        elif filename and "files" == upload:
            xfiles = {}
            webdav.mkdir(webdav_path)
            webdav.mkdir(os.path.join(
                webdav_path, f"{name}-{jobid}"))
            # FIXME fixed_path
            for root, subdirs, files in os.walk(sandbox):
                for subdir in subdirs:
                    xdir = os.path.join(
                        webdav_path,
                        f"{name}-{jobid}",
                        os.path.join(
                            root,
                            subdir)[
                            1 +
                            len(sandbox):])
                    mylog(f"mkdir {xdir}")
                    webdav.mkdir(xdir)
                for fname in files:
                    xfile = os.path.join(
                        webdav_path,
                        f"{name}-{jobid}",
                        os.path.join(
                            root,
                            fname)[
                            1 +
                            len(sandbox):])
                    xfiles[os.path.join(root, fname)] = xfile

            for fname in xfiles:
                webdav.upload_sync(xfiles[fname], fname)
        else:
            mylog("The build-in upload is skipped")

        mylog(f"Processing {jobid} is completed")

        if os.path.isfile(nodefile):
            os.unlink(nodefile)

        if os.path.isdir(tmpdir):
            rmtree(tmpdir)

        if os.path.isdir(sandbox):
            rmtree(sandbox)

    # Create a pull-based consumer
    sub = await js.pull_subscribe(args.queue, consumer, stream=sname)
    jobs = 0
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
            await qsub(msg)
            jobs += 1
        mylog(f"Number of processed jobs is {jobs}")
        if args.max_jobs and jobs == int(args.max_jobs):
            # FIXME clean exit
            mylog(f"Maximum number of jobs reached ({int(args.max_jobs)})")
            sys.exit(0)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    try:
        loop.run_forever()
    finally:
        loop.close()
