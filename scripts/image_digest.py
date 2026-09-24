"""Read the immutable image config digest from a single-image docker save stream.

Docker's classic and containerd stores can expose different inspect .Id semantics.
The config binds execution settings and every uncompressed filesystem layer hash.
"""
import hashlib
import json
import sys
import tarfile


def config_digest(stream):
    hashes = {}
    manifest = None
    with tarfile.open(fileobj=stream, mode='r|*') as archive:
        for entry in archive:
            if not entry.isfile() or entry.size > 8 * 1024 * 1024:
                continue
            data = archive.extractfile(entry).read()
            hashes[entry.name] = hashlib.sha256(data).hexdigest()
            if entry.name == 'manifest.json':
                manifest = json.loads(data)
    if manifest is None or len(manifest) != 1:
        raise ValueError('Expected exactly one image in docker save manifest')
    return 'sha256:' + hashes[manifest[0]['Config']]


if __name__ == '__main__':
    print(config_digest(sys.stdin.buffer))
