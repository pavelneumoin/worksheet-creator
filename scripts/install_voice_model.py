"""Install the pinned Apache-2.0 Russian Vosk model at image build time."""
import hashlib
from pathlib import Path
import sys
import tempfile
import urllib.request
import zipfile

URL='https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip'
SHA256='961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4'


def install(destination, archive=None):
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        path=Path(archive) if archive else Path(temporary)/'model.zip'
        if not archive:
            with urllib.request.urlopen(URL,timeout=60) as response, path.open('wb') as out:
                total=0
                while chunk:=response.read(1024*1024):
                    total+=len(chunk)
                    if total>60*1024*1024:raise ValueError('Unexpected model size')
                    out.write(chunk)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=SHA256:raise ValueError('Voice model checksum mismatch')
        with zipfile.ZipFile(path) as zip_file:
            for info in zip_file.infolist():
                if not (destination/info.filename).resolve().is_relative_to(destination):raise ValueError('Invalid model archive')
            zip_file.extractall(destination)
    print('Russian speech model installed; SHA256 verified.')

if __name__=='__main__':install(sys.argv[1] if len(sys.argv)>1 else '/opt',sys.argv[2] if len(sys.argv)>2 else None)
