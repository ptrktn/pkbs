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

cfg = {
    "syslog": False
}


# https://stackoverflow.com/a/3431838
def md5sum(fname):
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


"""
import logging
from http.client import HTTPConnection  # py3

log = logging.getLogger('urllib3')
log.setLevel(logging.DEBUG)

# logging from urllib3 to console
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
log.addHandler(ch)

# print statements from `http.client.HTTPConnection` to console/stdout
HTTPConnection.debuglevel = 1
"""

def webdav_mkdir(url, user, passwd, path):
    r = requests.request('MKCOL', f"{url}{path}", auth=(user, passwd))
    if 201 == print(r.status_code):
        print(f"Folder {folder} has been created")
    elif 405 == print(r.status_code):
        print(f"Folder {folder} already exists")
    elif 409 == print(r.status_code):
        print(f"Parent of folder {folder} does not exists")
    else:
        print(f"{r}")


def webdav_mkdirp(url, user, passwd, path):
    newpath = ""
    for i in path.split("/"):
        newpath = f"{newpath}/{i}"
        webdav_mkdir(url, user, passwd, newpath)


# FIXME retry
def webdav_upload(url, user, passwd, path, filename, mkdirs=True):
    if mkdirs:
        webdav_mkdirp(url, user, passwd, path)

    with open(filename, 'rb') as fp:
        data = fp.read()

    r = requests.put(
        f"{url}/{path}/{os.path.basename(filename)}",
        data=data,
        headers={
            'Content-type': 'application/octet-stream',
            'Slug': os.path.basename(filename)
        },
        auth=(user, passwd)
    )
    if r.status_code in [201, 204]:
        if r.headers.get("X-Hash-Md5"):
            md5_orig = md5sum(filename).lower()
            md5_dest = r.headers.get("X-Hash-Md5").lower()
            if md5_orig == md5_dest:
                print(f"File {filename} uploaded")
                return True
            else:
                print(f"File {filename} checksum mismatch: orig={m5d_orig} dest={md5_dest}")
    print(r.content)
    return False


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

    consumer = "workers"
    sname = f"{args.queue}-stream"
    
    # Create JetStream context
    js = nc.jetstream()

    # Persist messages on jobs' queue (i.e, subject in Jetstream).
    await js.add_stream(name=sname, subjects=[args.queue])

    def qsub(msg):
        mylog(f"QSUB {msg.subject} {msg.headers} LEN {len(msg.data)}")
        jobid = msg.headers["jobid"]
        name = msg.headers.get("name", "qsub")
        filename = msg.headers.get("filename")
        command = msg.headers.get("command")
        path = msg.headers.get("path", os.getenv("WEBDAV_PATH", "pkebs"))
        upload = msg.headers.get("upload", os.getenv("WEBDAV_UPLOAD", "zip"))
        
        if not(jobid):
            mylog("Jobs without jobid item in header will not be processed")
            return

        if filename:
            # FIXME clean sandbox
            sandbox = os.path.join("/var", "tmp", "pkebs", jobid)
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
        t1 = time.time()
        status = os.system(command)
        t2 = time.time()
        mylog(f"Job {jobid} exited with status {status} and the elapsed wallclock time was {round(t2 - t1, 2)} seconds")

        # FIXME zip, files, none
        user = os.getenv("WEBDAV_USER", "admin")
        passwd = os.getenv("WEBDAV_PASSWD", "admin")
        url = os.getenv("WEBDAV_URL", "http://nextcloud-svc/remote.php/dav/files")
        svc = f"{url}/{user}"

        if filename and "zip" == upload:
            zipname = os.path.join(os.path.dirname(sandbox), f"{jobid}.zip")
            zip_dir(zipname, sandbox)
            status = webdav_upload(svc, user, passwd, path, zipname)
            mylog(f"Upload: server {svc} user {user} path {path} file {zipname} success={status}")
            # FIXME cleanup
        elif filename and "files" == upload:
            for root, subdirs, files in os.walk(sandbox):
                for subdir in subdirs:
                    # FIXME
                    continue
                    xdir = os.path.join(path, jobid, os.path.join(root, subdir)[1+len(sandbox):])
                    mylog(f"mkdir {xdir}")
                    webdav_mkdir(svc, user, passwd, os.path.join("/", path, xdir))
                for fname in files:
                    xfile = os.path.join(path, jobid, os.path.join(root, fname)[1+len(sandbox):])
                    mylog(f"upload {xfile}")
                    webdav_upload(svc, user, passwd, os.path.dirname(xfile), os.path.join(root, fname), True)
        else:
            mylog("The build-in upload is skipped")
        mylog(f"Processing {jobid} is completed")

    # Create a pull-based consumer
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
            qsub(msg)
        

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    try:
        loop.run_forever()
    finally:
        loop.close()