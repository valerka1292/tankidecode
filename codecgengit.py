#!/usr/bin/env python3
import urllib.request
import email.utils
import subprocess
import shutil
import tarfile
import tempfile
import logging
import random
import json
import glob
import sys
import os

import codecgen

PIDFILE = '.pid'
BASE_URL = 'https://s.eu.tankionline.com/libs/'
MANIFEST = 'manifest.json'
WORKDIR = 'archive'
FFDEC = 'parallelSpeedUp=0,exportTimeout=86400,decompilationTimeoutFile=3600,decompilationTimeoutSingleMethod=600'
ORIGIN = 'git@github.com:XXLuigiMario/TankiOnlineCodecs.git'
ENV = {
    'GIT_AUTHOR_NAME': 'Joel Puig Rubio',
    'GIT_AUTHOR_EMAIL': 'joel.puig.rubio@gmail.com',
    'GIT_COMMITTER_NAME': 'Joel Puig Rubio',
    'GIT_COMMITTER_EMAIL': 'joel.puig.rubio@gmail.com'
}

def archive():
    os.makedirs(WORKDIR, exist_ok=True)
    manifest_file = os.path.join(WORKDIR, MANIFEST)
    latest, headers = urllib.request.urlretrieve(BASE_URL + MANIFEST + '?rand=' + str(random.random()))
    date = email.utils.parsedate_to_datetime(headers['Last-Modified'])
    tarball = os.path.join(WORKDIR, date.strftime('%Y-%m-%dT%H-%M-%S.tar.gz'))
    if os.path.exists(tarball):
        return None

    with open(latest, 'r') as f:
        data = json.load(f)
    with tarfile.open(tarball, 'w:gz', format=tarfile.GNU_FORMAT) as tar:
        info = tar.gettarinfo(name=latest, arcname=MANIFEST)
        info.mtime = date.timestamp()
        with open(latest, 'rb') as f:
            tar.addfile(tarinfo=info, fileobj=f)
        for path in data.values():
            tmp, headers = urllib.request.urlretrieve(BASE_URL + path)
            date = email.utils.parsedate_to_datetime(headers['Last-Modified'])
            info = tar.gettarinfo(name=tmp, arcname=os.path.basename(path))
            info.mtime = date.timestamp()
            with open(tmp, 'rb') as f:
                tar.addfile(tarinfo=info, fileobj=f)
            os.remove(tmp)

    shutil.move(latest, manifest_file)
    return tarball

def generate_from_tar(tarball):
    codecs_repo = os.path.join(WORKDIR, 'codecs')
    subprocess.check_call(['git', 'init', codecs_repo])
    subprocess.call(['git', 'remote', 'add', 'origin', ORIGIN], cwd=codecs_repo)

    p = subprocess.Popen(['java', '-jar', 'bin/ffdec/ffdec.jar', '-help'], stdout=subprocess.PIPE, text=True)
    decompiler = p.stdout.readline().rstrip()
    p.kill()

    to_scan = list()
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(tarball, 'r:gz') as tar:
            for member in tar:
                name = member.name
                if name.startswith('entrance') or name.startswith('game'):
                    tar.extract(member, path=tmp)
                    to_scan.append(name)

        for swf in to_scan:
            swf_file = os.path.join(tmp, swf)
            scripts, _ = os.path.splitext(swf_file)
            subprocess.check_call(['java', '-Xms384M', '-Xmx384M', '-jar', 'bin/ffdec/ffdec.jar', '-config', FFDEC, '-export', 'script', scripts, swf_file])

        comments = [f'Decompiler: {decompiler}'] + to_scan
        codecgen.generate(tmp, os.path.join(codecs_repo, 'codecs.py'), comments=comments)

    subprocess.check_call(['git', 'add', 'codecs.py'], cwd=codecs_repo)
    subprocess.check_call(['git', 'commit', '-m', 'update codecs'], cwd=codecs_repo, env=ENV)
    subprocess.check_call(['git', 'push', '-u', 'origin', 'master'], cwd=codecs_repo)

def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    logger = logging.getLogger()
    git_file = os.path.join(WORKDIR, 'git.json')

    try:
        with open(PIDFILE, 'r') as f:
            pid = int(f.read())
        os.kill(pid, 0)
    except OSError:
        with open(PIDFILE, 'w') as f:
            f.write(str(os.getpid()))
    else:
        sys.exit(0)

    try:
        with open(git_file, 'r') as f:
            git = json.load(f)
    except FileNotFoundError:
        git = list()

    tarball = archive()
    if tarball:
        logger.info(f'Archived new version in {tarball}')
    else:
        logger.info('No changes')

    # process any pending tarballs
    for fname in sorted(os.listdir(WORKDIR)):
        if fname.endswith('.tar.gz') and fname not in git:
            tarball = os.path.join(WORKDIR, fname)
            logger.info(f'Generating codec definitions from {tarball}')
            generate_from_tar(tarball)
            git.append(fname)            
            with open(git_file, 'w') as f:
                json.dump(git, f)

    os.remove(PIDFILE)

if __name__ == '__main__':
    main()
