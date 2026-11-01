"""Install the official Windows release and run AutoRemesher."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile


def ensure_executable(path):
    path = Path(path).resolve()
    if path.is_file():
        return path
    default = Path(__file__).resolve().parent / 'autoremesher' / 'autoremesher.exe'
    if path != default:
        raise FileNotFoundError(f'AutoRemesher not found: {path}')
    print('Downloading official AutoRemesher Windows release...', flush=True)
    def request(url):
        return urllib.request.Request(url, headers={'User-Agent': 'GLB-RemeshBake', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request('https://api.github.com/repos/huxingyi/autoremesher/releases/latest'), timeout=60) as response:
        release = json.load(response)
    asset = next((a for a in release['assets'] if a['name'].endswith('-win32-x86_64.zip')), None)
    if not asset:
        raise RuntimeError('Official release has no Windows x64 ZIP')
    with tempfile.TemporaryDirectory(prefix='autoremesher_install_') as temporary:
        temporary = Path(temporary)
        archive = temporary / 'release.zip'
        with urllib.request.urlopen(request(asset['browser_download_url']), timeout=120) as response, archive.open('wb') as output:
            shutil.copyfileobj(response, output)
        digest = asset.get('digest')
        if digest and digest.startswith('sha256:'):
            if hashlib.sha256(archive.read_bytes()).hexdigest() != digest.split(':', 1)[1]:
                raise RuntimeError('AutoRemesher download checksum mismatch')
        unpacked = temporary / 'unpacked'
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                destination = (unpacked / member.filename).resolve()
                if not destination.is_relative_to(unpacked.resolve()):
                    raise RuntimeError('Invalid path in release ZIP')
            package.extractall(unpacked)
        executable = next(unpacked.rglob('autoremesher.exe'), None)
        if executable is None:
            raise RuntimeError('Downloaded ZIP does not contain autoremesher.exe')
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(executable.parent, path.parent, dirs_exist_ok=True)
    return path


def run_remesher(executable, source, output, target_quads, timeout=1800):
    executable = ensure_executable(executable)
    environment = os.environ.copy()
    environment['QT_QPA_PLATFORM'] = 'offscreen'
    environment.pop('QT_PLUGIN_PATH', None)
    environment.pop('QT_QPA_PLATFORM_PLUGIN_PATH', None)
    hidden = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    try:
        probe = subprocess.run([str(executable), '--help'], cwd=executable.parent,
                               env=environment, capture_output=True, timeout=10, **hidden)
        cli = b'--input' in probe.stdout + probe.stderr
    except subprocess.TimeoutExpired:
        cli = False
    if cli:
        command = [str(executable), '--input', str(source), '--output', str(output),
                   '--target-quads', str(target_quads)]
        print('AUTOREMESHER ' + subprocess.list2cmdline(command), flush=True)
        subprocess.run(command, cwd=executable.parent, env=environment,
                       check=True, timeout=timeout, **hidden)
    else:
        print(f'AutoRemesher GUI mode: open {source}, remesh, export OBJ to {output}, then close AutoRemesher to continue baking.', flush=True)
        process = subprocess.Popen([str(executable), str(source)], cwd=executable.parent)
        try:
            process.wait(timeout=timeout)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f'AutoRemesher produced no OBJ. Expected: {output}')
