#!/usr/bin/env python3
"""Offline, process-isolated KPQC migration lab; OpenSSL performs all crypto."""
import base64
import copy
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import random
import select
import socket
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/camt.053.001.08.xsd"
NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"
ALGORITHMS = {"EC": 0, "haetae2": 2, "haetae3": 3, "haetae5": 5,
              "aimer128f": 1, "aimer192f": 3, "aimer256f": 5}
GROUPS = {"X25519": 0, "smaug1": 1, "smaug3": 3, "smaug5": 5,
          "ntruplus_kem576": None, "ntruplus_kem768": None,
          "ntruplus_kem864": None, "ntruplus_kem1152": None}
BASE_DIGEST = "sha256:3a833a303e49a4edb1faa4c8f2b55d224786568600c6b001ed1e6f8ab4a30d3d"


# 이미지 안의 라이브러리 메타데이터를 읽어 지원 알고리즘과 구현이 주장하는 보안 카테고리를 기록한다.
def library_metadata():
    # Read the stable prefix of OQS_KEM/OQS_SIG; record implementation claims,
    # never interpret them as independent security certification.
    class Prefix(ctypes.Structure):
        _fields_ = [("name", ctypes.c_char_p), ("version", ctypes.c_char_p), ("level", ctypes.c_uint8)]
    lib = ctypes.CDLL("/opt/liboqs-kpqc/lib/liboqs.so")
    result = []
    for kind in ("KEM", "SIG"):
        count = getattr(lib, f"OQS_{kind}_alg_count")
        count.restype = ctypes.c_size_t
        ident = getattr(lib, f"OQS_{kind}_alg_identifier")
        ident.argtypes, ident.restype = [ctypes.c_size_t], ctypes.c_char_p
        new, free = getattr(lib, f"OQS_{kind}_new"), getattr(lib, f"OQS_{kind}_free")
        new.argtypes, new.restype = [ctypes.c_char_p], ctypes.POINTER(Prefix)
        free.argtypes = [ctypes.POINTER(Prefix)]
        for i in range(count()):
            name = ident(i)
            if not any(s in name.decode().lower() for s in ("ntruplus", "smaug", "haetae", "aimer")):
                continue
            obj = new(name)
            if obj:
                result.append({"kind": kind, "name": obj.contents.name.decode(),
                               "version": obj.contents.version.decode(), "claimed_category": obj.contents.level})
                free(obj)
    return result


def run(args, *, data=None, check=True, cwd=None, resource_path=None):
    if resource_path is not None:
        args = measured_command(args, resource_path)
    p = subprocess.run([str(x) for x in args], input=data, capture_output=True,
                       timeout=15, cwd=cwd)
    if check and p.returncode:
        raise RuntimeError(f"{args[:3]}: {p.stderr.decode(errors='replace')[-1500:]}")
    return p


# OpenSSL 명령에 default와 oqsprovider를 함께 지정하는 공통 호출 경로다.
def ssl(command, *args, **kwargs):
    return run(["openssl", command, "-provider", "default", "-provider", "oqsprovider", *args], **kwargs)


def stats(values):
    v = sorted(values)
    return {"n": len(v), "p50_ms": round(v[math.ceil(len(v)*.50)-1], 3),
            "p95_ms": round(v[math.ceil(len(v)*.95)-1], 3),
            "min_ms": round(v[0], 3), "max_ms": round(v[-1], 3)}


def measured_command(args, path):
    return ["/usr/bin/time", "-f", "%U %S %M", "-o", str(path), *map(str, args)]


# 단계별 프로세스 자원을 읽는다. 최대 RSS는 프로세스 수명 전체의 최대값이며 단계별 최대값을 합산하지 않는다.
def process_resources(path):
    # GNU time prints CPU seconds with two decimal places; retain this limit.
    user, system, rss = path.read_text().strip().splitlines()[-1].split()
    return {"user_cpu_ms": round(float(user) * 1000, 3),
            "system_cpu_ms": round(float(system) * 1000, 3),
            "total_cpu_ms": round((float(user) + float(system)) * 1000, 3),
            "max_rss_kib": int(rss), "cpu_display_resolution_ms": 10}


# 공개 camt.053 XSD에 맞춘 합성 거래 데이터를 만든다. 실제 고객 데이터나 은행 정산 업무의 완전한 재현은 아니다.
def statement():
    ET.register_namespace("", NS)
    def add(parent, name, value=None, **attrs):
        node = ET.SubElement(parent, f"{{{NS}}}{name}", attrs)
        if value is not None:
            node.text = str(value)
        return node
    root = ET.Element(f"{{{NS}}}Document")
    body = add(root, "BkToCstmrStmt")
    header = add(body, "GrpHdr")
    add(header, "MsgId", "LAB-MSG-20260923-001")
    add(header, "CreDtTm", "2026-09-23T09:00:00Z")
    stmt = add(body, "Stmt")
    add(stmt, "Id", "LAB-STMT-20260923-001")
    add(stmt, "CreDtTm", "2026-09-23T09:00:00Z")
    account = add(stmt, "Acct")
    add(add(add(account, "Id"), "Othr"), "Id", "SYNTHETIC-ACCOUNT-001")
    add(account, "Ccy", "KRW")
    add(account, "Nm", "SYNTHETIC ACCOUNT - NOT A REAL CUSTOMER")
    transactions = [("CRDT", 100000), ("DBIT", 20000), ("CRDT", 250000)]
    for code, amount in [("OPBD", 1000000), ("CLBD", 1330000)]:
        bal = add(stmt, "Bal")
        add(add(add(bal, "Tp"), "CdOrPrtry"), "Cd", code)
        add(bal, "Amt", amount, Ccy="KRW")
        add(bal, "CdtDbtInd", "CRDT")
        add(add(bal, "Dt"), "Dt", "2026-09-23")
    for i, (direction, amount) in enumerate(transactions):
        entry = add(stmt, "Ntry")
        add(entry, "NtryRef", f"LAB-TX-{i+1:03}")
        add(entry, "Amt", amount, Ccy="KRW")
        add(entry, "CdtDbtInd", direction)
        add(add(entry, "Sts"), "Cd", "BOOK")
        add(add(entry, "BookgDt"), "Dt", "2026-09-23")
        # Proprietary code is explicitly a lab code, not a bank business code.
        proprietary = add(add(entry, "BkTxCd"), "Prtry")
        add(proprietary, "Cd", "LAB-CREDIT" if direction == "CRDT" else "LAB-DEBIT")
        add(proprietary, "Issr", "KPQC-LAB")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class Rejected(Exception):
    pass


# 스키마 형식 검사와 실험용 잔액 일관성 검사를 구분한다. 형식 통과만으로 실제 서비스 업무 적합성을 주장하지 않는다.
def validate_xml(data, work, resource_path=None):
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise Rejected("xml_entities")
    file = work / "validate.xml"
    file.write_bytes(data)
    p = run(["xmllint", "--nonet", "--noout", "--schema", SCHEMA, file], check=False,
            resource_path=resource_path)
    if p.returncode:
        raise Rejected("schema")
    r = ET.fromstring(data)
    n = {"n": NS}
    stmts = r.findall("n:BkToCstmrStmt/n:Stmt", n)
    if len(stmts) != 1:
        raise Rejected("account_scope")
    s = stmts[0]
    def text(node, path):
        value = node.findtext(path, namespaces=n)
        if value is None:
            raise Rejected("missing_field")
        return value
    if text(s, "n:Acct/n:Ccy") != "KRW":
        raise Rejected("currency")
    for amount in s.findall(".//n:Amt", n):
        if amount.get("Ccy") != "KRW" or Decimal(amount.text) != Decimal(amount.text).to_integral_value():
            raise Rejected("currency")
    def signed(node):
        return Decimal(text(node, "n:Amt")) * (1 if text(node, "n:CdtDbtInd") == "CRDT" else -1)
    balances = {}
    for b in s.findall("n:Bal", n):
        code = text(b, "n:Tp/n:CdOrPrtry/n:Cd")
        if code in balances:
            raise Rejected("duplicate_balance")
        balances[code] = signed(b)
    entries = s.findall("n:Ntry", n)
    refs = [text(e, "n:NtryRef") for e in entries]
    if len(refs) != len(set(refs)) or any(text(e, "n:Sts/n:Cd") != "BOOK" for e in entries):
        raise Rejected("entries")
    if set(balances) != {"OPBD", "CLBD"} or balances["OPBD"] + sum(map(signed, entries)) != balances["CLBD"]:
        raise Rejected("balance")
    return {"document_id": text(s, "n:Id"), "entries": len(entries),
            "opening": str(balances["OPBD"]), "closing": str(balances["CLBD"])}


# 로컬 카나리 실험용 TCP 중계기다. 신규 접속 일부를 PQC 서버로 보내고 장애·차단 정책을 시험한다.
class Router:
    """Deterministic 10-connection scheduling, TLS passthrough; no silent failover."""
    def __init__(self, legacy, pqc):
        self.legacy, self.pqc = legacy, pqc
        self.percent, self.counter, self.blocked = 0, 0, False
        self.events = []
        self.lock = threading.Lock()
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen()
        self.closed = False
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def configure(self, percent, blocked=False):
        with self.lock:
            self.percent, self.blocked, self.counter = percent, blocked, 0

    def serve(self):
        while not self.closed:
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            with self.lock:
                target = self.pqc if self.counter % 10 < self.percent // 10 else self.legacy
                self.counter += 1
                blocked = self.blocked
                self.events.append({"time_ns": time.monotonic_ns(), "target": target, "blocked": blocked})
            threading.Thread(target=self.relay, args=(client, target, blocked), daemon=True).start()

    @staticmethod
    def relay(client, target, blocked):
        with client:
            if blocked:
                return
            try:
                with socket.create_connection(("127.0.0.1", target), timeout=3) as upstream:
                    client.settimeout(3)
                    upstream.settimeout(3)
                    while True:
                        ready, _, _ = select.select([client, upstream], [], [], 5)
                        if not ready:
                            return
                        for source in ready:
                            packet = source.recv(65536)
                            if not packet:
                                return
                            (upstream if source is client else client).sendall(packet)
            except OSError:
                return

    def close(self):
        self.closed = True
        # Wake a blocking accept before closing; otherwise descriptor reuse can
        # let the previous router consume the new router's first connection.
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise RuntimeError("router accept thread did not stop")


# 초기 파일 서명·전송 실험의 본체다. execute()가 정상/변조/호환성/단계적 전환 시험을 순서대로 실행한다.
class Lab:
    def __init__(self, work, out):
        self.work, self.out = work, out
        self.public = work / "public"
        self.public.mkdir()
        self.keys = work / "keys"
        self.keys.mkdir(mode=0o700)
        self.logs = out / "logs"
        self.logs.mkdir()
        self.processes = []
        self.trust = {}
        self.tests, self.requests = [], []
        self.seen = set()
        self.result = {"status": "running", "tests": self.tests, "requests": self.requests}

    def record(self, name, passed, **detail):
        self.tests.append({"name": name, "passed": bool(passed), **detail})
        print(f"{'PASS' if passed else 'FAIL'} {name}", flush=True)
        if not passed:
            raise AssertionError(name)

    # 예상한 오류로 거부되어야 시험 성공이다. 변조 데이터가 정상 처리되면 오히려 시험 실패다.
    def reject(self, name, fn, expected):
        try:
            fn()
        except Rejected as e:
            self.record(name, str(e) == expected, reason=str(e))
        else:
            self.record(name, False, reason="unexpected_accept")

    def keygen(self, alg):
        private, public = self.keys / f"{alg}.pem", self.keys / f"{alg}.pub.pem"
        args = ["-algorithm", alg]
        if alg == "EC":
            args += ["-pkeyopt", "ec_paramgen_curve:P-256"]
        ssl("genpkey", *args, "-out", private)
        ssl("pkey", "-in", private, "-pubout", "-out", public)
        self.trust[alg] = public

    # 파일과 알고리즘·문서 ID 등 메타데이터를 함께 서명한다. base64는 JSON 운반용 인코딩이며 암호화가 아니다.
    def sign(self, alg, xml, document_id="LAB-STMT-20260923-001", resource_path=None):
        message = json.dumps({"domain": "KPQC-LAB-STATEMENT-v1", "algorithm": alg,
                              "key_id": alg, "policy_version": 1, "document_id": document_id,
                              "payload_b64": base64.b64encode(xml).decode()},
                             sort_keys=True, separators=(",", ":")).encode()
        (self.work / "message.bin").write_bytes(message)
        start = time.perf_counter()
        ssl("pkeyutl", "-sign", "-rawin", *(["-digest", "sha256"] if alg == "EC" else []),
            "-inkey", self.keys / f"{alg}.pem", "-in", self.work / "message.bin", "-out", self.work / "signature.bin",
            resource_path=resource_path)
        elapsed = (time.perf_counter() - start) * 1000
        sig = (self.work / "signature.bin").read_bytes()
        return {"message_b64": base64.b64encode(message).decode(), "signature_b64": base64.b64encode(sig).decode()}, elapsed, len(sig)

    # 허용 알고리즘·신뢰 공개키 → 서명 → XML/문서 ID → 선택적 중복 검사 순으로 검증한다.
    def receive(self, bundle, allowed, replay=False, trust=None, resource_paths=None):
        resource_paths = resource_paths or {}
        message = base64.b64decode(bundle["message_b64"], validate=True)
        m = json.loads(message)
        if m["domain"] != "KPQC-LAB-STATEMENT-v1" or m["policy_version"] != 1:
            raise Rejected("domain_policy")
        if m["algorithm"] not in allowed or m["key_id"] != m["algorithm"]:
            raise Rejected("algorithm_policy")
        registry = self.trust if trust is None else trust
        if m["key_id"] not in registry:
            raise Rejected("untrusted_key")
        (self.work / "verify.bin").write_bytes(message)
        (self.work / "verify.sig").write_bytes(base64.b64decode(bundle["signature_b64"], validate=True))
        p = ssl("pkeyutl", "-verify", "-rawin", *(["-digest", "sha256"] if m["algorithm"] == "EC" else []),
                "-pubin", "-inkey", registry[m["key_id"]], "-in", self.work / "verify.bin",
                "-sigfile", self.work / "verify.sig", check=False,
                resource_path=resource_paths.get("verify"))
        if p.returncode:
            raise Rejected("signature")
        validated = validate_xml(base64.b64decode(m["payload_b64"], validate=True), self.work,
                                 resource_path=resource_paths.get("xml"))
        if m["document_id"] != validated["document_id"]:
            raise Rejected("document_binding")
        if replay:
            if m["document_id"] in self.seen:
                raise Rejected("duplicate")
            self.seen.add(m["document_id"])
        return validated

    # 이 초기 실험은 TLS 인증서를 EC로 고정하고 PQC 파일 서명과 KEM 전환을 관찰한다.
    def cert(self):
        ssl("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
            "-keyout", self.keys / "tls.pem", "-out", self.work / "tls.crt", "-days", "1",
            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost")

    def server(self, group, port, resource_path=None):
        log = open(self.logs / f"server-{group}-{port}.log", "ab")
        args = ["openssl", "s_server", "-provider", "default", "-provider", "oqsprovider",
                              "-accept", f"127.0.0.1:{port}", "-cert", str(self.work / "tls.crt"),
                              "-key", str(self.keys / "tls.pem"), "-groups", group,
                              "-tls1_3", "-ciphersuites", "TLS_AES_256_GCM_SHA384", "-WWW", "-quiet"]
        if resource_path is not None:
            args = measured_command(args + ["-naccept", "1"], resource_path)
        p = subprocess.Popen(args, cwd=self.public, stdout=log, stderr=log,
                             start_new_session=True)
        log.close()
        self.processes.append(p)
        for _ in range(100):
            if p.poll() is not None:
                raise RuntimeError(f"server {group} exited")
            if resource_path is not None:
                # Do not consume the sole connection with a readiness probe.
                rows = Path("/proc/net/tcp").read_text().splitlines()[1:]
                if any(row.split()[1] == f"0100007F:{port:04X}" and row.split()[3] == "0A" for row in rows):
                    return p
                time.sleep(.02)
                continue
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1):
                    return p
            except OSError:
                time.sleep(.02)
        raise RuntimeError("server readiness timeout")

    # OpenSSL 프로세스 시작부터 TLS+HTTP 응답까지 포함한다. 순수 TLS 측정은 tls_handshake.c를 본다.
    def request(self, port, groups, *, host="localhost", ca=None, label="request"):
        seq = len(self.requests)
        trace = self.logs / f"tls-{seq:04}.trace"
        args = ["s_client", "-connect", f"127.0.0.1:{port}", "-servername", "localhost",
                "-verify_hostname", host, "-verify_return_error", "-CAfile", ca or self.work / "tls.crt",
                "-groups", groups, "-tls1_3", "-ciphersuites", "TLS_AES_256_GCM_SHA384",
                "-brief", "-ign_eof", "-trace", "-msgfile", trace]
        start = time.perf_counter()
        resource_path = self.logs / f"tls-{seq:04}.client.resources"
        p = run(measured_command(["openssl", args[0], "-provider", "default", "-provider", "oqsprovider", *args[1:]], resource_path),
                data=b"GET /bundle.json HTTP/1.0\r\nHost: localhost\r\n\r\n", check=False)
        ms = (time.perf_counter() - start) * 1000
        log = p.stderr.decode(errors="replace")
        (self.logs / f"tls-{seq:04}.stderr").write_text(log)
        body = p.stdout.split(b"\r\n\r\n", 1)
        ok = p.returncode == 0 and "Verification: OK" in log and p.stdout.startswith(b"HTTP/1.0 200") and len(body) == 2
        rec = {"id": seq, "label": label, "allowed_groups": groups, "port": port,
               "success": ok, "client_process_ms": round(ms, 3), "trace": str(trace.relative_to(self.out)),
               "client_resources": process_resources(resource_path)}
        # Decode ServerHello's key_share group from the official trace output.
        trace_text = trace.read_text() if trace.exists() else ""
        server_hello = trace_text.split("ServerHello,", 1)[-1].split("Received Record", 1)[0] if "ServerHello," in trace_text else ""
        match = re.search(r"(?:NamedGroup|named_group):\s*([^\n]+)", server_hello)
        rec["server_group_trace"] = match.group(1).strip() if match else None
        self.requests.append(rec)
        return ok, (json.loads(body[1]) if ok else None), rec

    def execute(self):
        schema_source = json.loads((SCHEMA.parent / "source.json").read_text())
        self.record("schema_source_checksum", hashlib.sha256(SCHEMA.read_bytes()).hexdigest() == schema_source["sha256"])
        xml = statement()
        (self.out / "statement.xml").write_bytes(xml)
        self.result["environment"] = {"utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
            "openssl": run(["openssl", "version"]).stdout.decode().strip(),
            "providers": ssl("list", "-providers").stdout.decode(), "base_digest": BASE_DIGEST,
            "schema_sha256": hashlib.sha256(SCHEMA.read_bytes()).hexdigest(),
            "sample_sha256": hashlib.sha256(xml).hexdigest(), "cpu_limit": 2, "memory_limit_mib": 512,
            "lab_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "measurement": "sequential fresh TLS connections; subprocess wall time includes startup, TLS and HTTP; not isolated handshake time"}
        self.result["library_metadata"] = library_metadata()
        for group in GROUPS:
            if group.startswith("ntruplus"):
                size = re.search(r"\d+$", group).group()
                matches = [m for m in self.result["library_metadata"] if m["kind"] == "KEM" and "ntru" in m["name"].lower() and m["name"].endswith(size)]
                if len(matches) == 1:
                    GROUPS[group] = matches[0]["claimed_category"]
        self.record("official_xsd_and_balance", validate_xml(xml, self.work)["closing"] == "1330000")
        self.reject("schema_rejects_invalid_currency", lambda: validate_xml(xml.replace(b'Ccy="KRW"', b'Ccy="INVALID"'), self.work), "schema")
        self.reject("business_rejects_balance_mismatch", lambda: validate_xml(xml.replace(b"1330000", b"1330001"), self.work), "balance")
        signatures, bundles = {}, {}
        for alg in ALGORITHMS:
            self.keygen(alg)
            signs, verifies, sizes = [], [], []
            for _ in range(5):
                bundle, elapsed, size = self.sign(alg, xml)
                signs.append(elapsed)
                sizes.append(size)
                start = time.perf_counter()
                self.receive(bundle, {alg})
                verifies.append((time.perf_counter() - start) * 1000)
            signatures[alg] = {"category": ALGORITHMS[alg], "sign_process": stats(signs),
                               "verify_plus_xml_process": stats(verifies), "signature_bytes": sizes}
            bundles[alg] = bundle
            bad = copy.deepcopy(bundle)
            # Keep policy valid but alter the signed payload bytes.
            m = json.loads(base64.b64decode(bundle["message_b64"]))
            m["payload_b64"] = base64.b64encode(xml.replace(b"1000000", b"9000000")).decode()
            bad["message_b64"] = base64.b64encode(json.dumps(m).encode()).decode()
            self.reject(f"{alg}_tamper_rejection", lambda: self.receive(bad, {alg}), "signature")
            self.record(f"{alg}_five_roundtrips", True)
        self.result["signatures"] = signatures
        bundle = bundles["haetae2"]
        self.reject("policy_rejects_classical_signature", lambda: self.receive(bundles["EC"], {"haetae2"}), "algorithm_policy")
        self.reject("untrusted_key_rejected", lambda: self.receive(bundle, {"haetae2"}, trust={}), "untrusted_key")
        # Same algorithm, independent wrong key: a genuine verification failure.
        ssl("genpkey", "-algorithm", "haetae2", "-out", self.keys / "wrong.pem")
        ssl("pkey", "-in", self.keys / "wrong.pem", "-pubout", "-out", self.keys / "wrong.pub")
        self.reject("wrong_same_algorithm_key", lambda: self.receive(bundle, {"haetae2"}, trust={"haetae2": self.keys / "wrong.pub"}), "signature")
        self.receive(bundle, {"haetae2"}, replay=True)
        self.reject("duplicate_document_rejected", lambda: self.receive(bundle, {"haetae2"}, replay=True), "duplicate")
        self.record("receiver_first_migration", all(self.receive(bundles[a], {"EC", "haetae2"}) for a in ("EC", "haetae2")))
        self.reject("incompatible_receiver_rollback_blocked", lambda: self.receive(bundle, {"EC"}), "algorithm_policy")
        (self.public / "bundle.json").write_text(json.dumps(bundle))
        (self.out / "signed-bundle.json").write_text(json.dumps(bundle, indent=2))
        pub = self.out / "public-keys"
        pub.mkdir()
        for alg, path in self.trust.items():
            (pub / f"{alg}.pem").write_bytes(path.read_bytes())
        self.cert()
        ports = {group: 24000+i for i, group in enumerate(GROUPS)}
        servers = {group: self.server(group, port) for group, port in ports.items()}
        tls = {}
        for group, port in ports.items():
            timings, observed = [], []
            for i in range(12):
                ok, downloaded, rec = self.request(port, group, label=f"baseline-{group}")
                self.record(f"tls_{group}_{i}", ok and downloaded == bundle)
                self.receive(downloaded, {"haetae2"})
                timings.append(rec["client_process_ms"])
                observed.append(rec["server_group_trace"])
            tls[group] = {"category": GROUPS[group], "client_process": stats(timings), "server_groups": sorted(set(observed), key=str)}
        self.result["tls"] = tls
        expected_codes = {"X25519": 29, "smaug1": 65056, "smaug3": 65059, "smaug5": 65062,
                          "ntruplus_kem576": 65064, "ntruplus_kem768": 65067,
                          "ntruplus_kem864": 65070, "ntruplus_kem1152": 65073}
        for group, entry in tls.items():
            self.record(f"negotiated_group_{group}", all(value is not None and f"({expected_codes[group]})" in value for value in entry["server_groups"]))
        # Hold the TLS authentication certificate fixed; these are KEM + file
        # signature categories, not a claim of end-to-end PQ TLS authentication.
        combined = [{"kem": g, "signature": a, "sessions": []}
                    for g in GROUPS if g != "X25519" for a in ALGORITHMS if a != "EC"]
        combined.insert(0, {"kem": "X25519", "signature": "EC", "sessions": []})
        self.result["combined_profiles"] = combined
        self.result["combination_measurement"] = {
            "repeats": 5, "order_seed": 20260923,
            "scope": "one fresh file signature, single-connection TLS server/client, signature verification and XML validation per session; process initialization included; key/certificate generation excluded",
            "cpu": "sum of five measured child-process CPU times; Python controller and GNU time overhead excluded; each user/system field displayed at 10 ms resolution",
            "memory": "per-stage process lifetime maximum RSS in KiB; peaks are never summed; not incremental cryptographic memory"}
        # 실행 순서에 따른 영향을 줄이도록 조합 순서를 고정 시드로 섞고, KEM×서명 조합별 자원을 따로 수집한다.
        rng = random.Random(20260923)
        for repeat in range(5):
            order = list(combined)
            rng.shuffle(order)
            for profile in order:
                group, alg = profile["kem"], profile["signature"]
                sid = f"{group}-{alg}-{repeat}"
                paths = {stage: self.logs / f"session-{sid}-{stage}.resources"
                         for stage in ("sign", "server", "verify", "xml")}
                start = time.perf_counter()
                fresh, sign_ms, sig_bytes = self.sign(alg, xml, resource_path=paths["sign"])
                payload = json.dumps(fresh).encode()
                (self.public / "bundle.json").write_bytes(payload)
                server_start = time.perf_counter()
                single = self.server(group, 25000, resource_path=paths["server"])
                ready_ms = (time.perf_counter() - server_start) * 1000
                ok, downloaded, rec = self.request(25000, group, label=f"combination-{sid}")
                exit_code = single.wait(timeout=15)
                server_ms = (time.perf_counter() - server_start) * 1000
                self.record(f"combined_transfer_{sid}", ok and downloaded == fresh and exit_code == 0
                            and f"({expected_codes[group]})" in (rec["server_group_trace"] or ""))
                verify_start = time.perf_counter()
                validated = self.receive(downloaded, {alg}, resource_paths=paths)
                verify_ms = (time.perf_counter() - verify_start) * 1000
                elapsed = (time.perf_counter() - start) * 1000
                resources = {stage: process_resources(path) for stage, path in paths.items()}
                resources["client"] = rec["client_resources"]
                self.record(f"combined_validated_{sid}", validated["entries"] == 3 and all(
                    r["max_rss_kib"] > 0 and r["total_cpu_ms"] >= 0 for r in resources.values()))
                profile["sessions"].append({"session_id": sid, "repeat": repeat, "request_id": rec["id"],
                    "passed": True, "signature_bytes": sig_bytes, "envelope_bytes": len(payload),
                    "workflow_wall_ms": round(elapsed, 3), "sign_process_ms": round(sign_ms, 3),
                    "server_start_to_ready_ms": round(ready_ms, 3), "server_lifecycle_wall_ms": round(server_ms, 3),
                    "client_process_ms": rec["client_process_ms"], "verify_plus_xml_wall_ms": round(verify_ms, 3),
                    "resources": resources, "measured_process_cpu_ms": round(sum(r["total_cpu_ms"] for r in resources.values()), 3)})
        self.record("combination_matrix_complete", len(combined) == 43 and all(len(p["sessions"]) == 5 for p in combined))
        (self.public / "bundle.json").write_text(json.dumps(bundle))
        for name, kwargs in [("hostname_rejected", {"host": "wrong.invalid"}),
                              ("unsupported_peer_group_rejected", {"groups": "X25519"})]:
            groups = kwargs.pop("groups", "smaug1")
            ok, _, _ = self.request(ports["smaug1"], groups, label=name, **kwargs)
            self.record(name, not ok)
        ssl("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
            "-keyout", self.keys / "untrusted.pem", "-out", self.work / "untrusted.crt", "-days", "1", "-subj", "/CN=Untrusted")
        ok, _, _ = self.request(ports["smaug1"], "smaug1", ca=self.work / "untrusted.crt", label="untrusted_certificate")
        self.record("untrusted_certificate_rejected", not ok)
        p = ssl("s_client", "-groups", "not_a_real_group", "-connect", "127.0.0.1:1", check=False)
        self.record("invalid_group_gate", p.returncode != 0 and b"group" in p.stderr.lower())
        p = run(["openssl", "list", "-providers", "-provider", "/no-such-provider.so"], check=False)
        self.record("missing_provider_gate", p.returncode != 0)
        router = Router(ports["X25519"], ports["smaug1"])
        self.router = router
        rollout = []
        # Functional gate plus generous lab-only latency bound; not a bank SLO.
        threshold = max(2000, 3 * tls["X25519"]["client_process"]["p95_ms"])
        # 단계별 20개 신규 연결에서 실제 협상 결과와 전달 성공을 확인한다. 운영 환경의 성능 SLO는 아니다.
        for pct in [10, 50, 100]:
            router.configure(pct)
            start_event = len(router.events)
            rows = []
            for _ in range(20):
                ok, downloaded, rec = self.request(router.port, "smaug1:X25519", label=f"canary-{pct}")
                if ok:
                    self.receive(downloaded, {"haetae2"})
                rows.append(rec)
            chosen = router.events[start_event:]
            pqc_count = sum(e["target"] == ports["smaug1"] for e in chosen)
            pqc_observed = sum(r["server_group_trace"] == "UNKNOWN (65056)" for r in rows)
            passed = all(r["success"] for r in rows) and max(r["client_process_ms"] for r in rows) < threshold and pqc_count == pct//5 and pqc_observed == pqc_count
            rollout.append({"percent": pct, "requests": len(rows), "pqc_connections": pqc_count,
                            "passed": passed, "negotiated_pqc": pqc_observed, "latency_limit_ms": threshold})
            self.record(f"canary_{pct}_gate", passed)
        self.result["rollout"] = rollout
        # Traffic-driven detection: stop the PQC process, detect on next request.
        failure_start = time.perf_counter()
        servers["smaug1"].terminate()
        servers["smaug1"].wait(timeout=5)
        ok, _, _ = self.request(router.port, "smaug1:X25519", label="injected_server_failure")
        detected = time.perf_counter()
        self.record("server_failure_detected", not ok)
        # 고전 KEM 복귀가 허용된 정책에서는 기존 경로로 복귀한다. 파일 서명까지 고전 방식으로 바꾸는 것은 아니다.
        router.configure(0)
        ok, downloaded, _ = self.request(router.port, "smaug1:X25519", label="allowed_rollback")
        if ok:
            self.receive(downloaded, {"haetae2"})
        recovered = time.perf_counter()
        self.record("transition_policy_recovers", ok)
        self.result["recovery"] = {"detection_ms": round((detected-failure_start)*1000, 3),
            "recovery_from_detection_ms": round((recovered-detected)*1000, 3),
            "failure_to_success_ms": round((recovered-failure_start)*1000, 3), "failed_probes": 1,
            "trigger": "next synthetic request, not continuous monitoring"}
        # PQC 필수 정책에서는 고전 방식으로 조용히 우회하지 않고 연결을 차단하는 fail-closed를 검증한다.
        router.configure(100, blocked=True)
        before = len(router.events)
        ok, _, _ = self.request(router.port, "smaug1", label="pqc_required_fail_closed")
        self.record("pqc_required_no_classical_fallback", not ok and all(e["blocked"] for e in router.events[before:]))
        self.server("smaug1", ports["smaug1"])
        router.configure(100)
        ok, downloaded, _ = self.request(router.port, "smaug1", label="pqc_restored")
        self.record("pqc_required_recovery", ok and self.receive(downloaded, {"haetae2"})["entries"] == 3)
        self.result["router_events"] = router.events
        # Repeat progressive delivery and failure handling with the other KEM
        # family, rather than claiming SMAUG's rollout result covers NTRU+.
        router.close()
        router = Router(ports["X25519"], ports["ntruplus_kem768"])
        self.router = router
        ntru_rollout = []
        for pct in [10, 50, 100]:
            router.configure(pct)
            before = len(router.events)
            rows = []
            for _ in range(20):
                ok, downloaded, rec = self.request(router.port, "ntruplus_kem768:X25519", label=f"ntru-canary-{pct}")
                if ok:
                    self.receive(downloaded, {"haetae2"})
                rows.append(rec)
            chosen = router.events[before:]
            count = sum(e["target"] == ports["ntruplus_kem768"] for e in chosen)
            pqc_observed = sum(r["server_group_trace"] == "UNKNOWN (65067)" for r in rows)
            passed = all(r["success"] for r in rows) and max(r["client_process_ms"] for r in rows) < threshold and count == pct//5 and pqc_observed == count
            self.record(f"ntru_canary_{pct}_gate", passed)
            ntru_rollout.append({"percent": pct, "requests": len(rows), "pqc_connections": count, "negotiated_pqc": pqc_observed, "passed": passed})
        self.result["ntru_rollout"] = ntru_rollout
        failure_start = time.perf_counter()
        servers["ntruplus_kem768"].terminate()
        servers["ntruplus_kem768"].wait(timeout=5)
        ok, _, _ = self.request(router.port, "ntruplus_kem768:X25519", label="ntru_server_failure")
        detected = time.perf_counter()
        self.record("ntru_server_failure_detected", not ok)
        router.configure(0)
        ok, downloaded, _ = self.request(router.port, "ntruplus_kem768:X25519", label="ntru_allowed_rollback")
        if ok:
            self.receive(downloaded, {"haetae2"})
        recovered = time.perf_counter()
        self.record("ntru_transition_policy_recovers", ok)
        self.result["ntru_recovery"] = {"detection_ms": round((detected-failure_start)*1000, 3),
            "recovery_from_detection_ms": round((recovered-detected)*1000, 3),
            "failure_to_success_ms": round((recovered-failure_start)*1000, 3), "failed_probes": 1}
        router.configure(100, blocked=True)
        before = len(router.events)
        ok, _, _ = self.request(router.port, "ntruplus_kem768", label="ntru_pqc_required_block")
        self.record("ntru_pqc_required_no_fallback", not ok and all(e["blocked"] for e in router.events[before:]))
        self.server("ntruplus_kem768", ports["ntruplus_kem768"])
        router.configure(100)
        ok, downloaded, _ = self.request(router.port, "ntruplus_kem768", label="ntru_restored")
        self.record("ntru_pqc_required_recovery", ok and self.receive(downloaded, {"haetae2"})["entries"] == 3)
        self.result["ntru_router_events"] = router.events
        self.result["status"] = "passed"

    def close(self):
        if hasattr(self, "router"):
            self.router.close()
        for p in self.processes:
            if p.poll() is None:
                # Include GNU time's OpenSSL child when cleaning up a failure.
                import signal
                os.killpg(p.pid, signal.SIGTERM)
                p.wait(timeout=5)


def main():
    os.umask(0o077)
    out = Path(os.environ.get("RESULTS_DIR", "/results")) / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="kpqc-lab-") as temp:
        lab = Lab(Path(temp), out)
        try:
            lab.execute()
        except Exception as e:
            lab.result["status"] = "failed"
            lab.result["error"] = repr(e)
            raise
        finally:
            lab.close()
            # 컨테이너 전체 누적 통계는 보조 관측이다. 알고리즘 조합별 비용은 sessions의 단계별 프로세스 결과를 사용한다.
            lab.result["container_resources"] = {}
            for name in ("cpu.max", "cpu.stat", "memory.max", "memory.peak"):
                path = Path("/sys/fs/cgroup") / name
                if path.exists():
                    lab.result["container_resources"][name] = path.read_text().strip()
            (out / "results.json").write_text(json.dumps(lab.result, ensure_ascii=False, indent=2))
            print(f"RESULTS: {out}", flush=True)


if __name__ == "__main__":
    main()
