"""Read the immutable image config digest from a single-image docker save stream.

Docker's classic and containerd stores can expose different inspect .Id semantics.
The config binds execution settings and every uncompressed filesystem layer hash.
"""
import hashlib
import json
import sys
import tarfile


# docker save의 tar를 풀어 파일로 만들지 않고 순서대로 읽는다. 단일 이미지의 config 내용을 SHA-256으로 계산한다.
# config 안에는 실행 설정과 rootfs 계층 해시가 있어 Docker 저장 방식이 달라도 같은 내용을 비교할 수 있다.
def config_digest(stream):
    hashes = {}
    manifest = None
    with tarfile.open(fileobj=stream, mode='r|*') as archive:
        for entry in archive:
            # 큰 레이어 본문은 메모리에 올리지 않는다. manifest와 작은 config 파일의 해시만 필요하다.
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
