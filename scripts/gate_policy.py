"""Policy evaluation for trusted lab probe evidence; no provider dependency."""

def check(r, policy):
    if not isinstance(r, dict) or type(r.get('success')) is not bool:
        return 'INVALID_PROBE_EVIDENCE'
    if r.get('transport_errors') or r.get('probe_error'):
        return 'PROBE_UNAVAILABLE'
    if not r['success'] or r.get('returncode') != 0:
        return 'TLS_HANDSHAKE_FAILED'
    fields = {'verify_result': int, 'group_code': int, 'signature_code': int,
              'tls_version': str, 'cipher': str}
    if any(type(r.get(k)) is not t for k,t in fields.items()):
        return 'INVALID_PROBE_EVIDENCE'
    if policy['require_certificate_verification'] and r['verify_result'] != 0:
        return 'CERTIFICATE_VERIFICATION_FAILED'
    for key,reason in [('tls_version','TLS_VERSION_MISMATCH'),('group_code','KEM_POLICY_MISMATCH'),
                       ('signature_code','SIGNATURE_POLICY_MISMATCH'),('cipher','CIPHER_POLICY_MISMATCH')]:
        if r[key] != policy[key]:
            return reason
    return None


def evaluate(q, policy):
    """Missing probes and transport failures must never count as negative-test success."""
    reasons = []
    if q.get('ready') is not True:
        reasons.append('CANDIDATE_NOT_READY')
    probes = q.get('probes')
    if not isinstance(probes, dict):
        probes = {}
        reasons.append('INVALID_PROBE_EVIDENCE')
    for client in policy['required_clients']:
        reason = check(probes.get(client), policy)
        if reason:
            reasons.append(reason)
    if not policy['allow_classical_fallback']:
        for client in policy['forbidden_clients']:
            r = probes.get(client)
            if not isinstance(r, dict):
                reasons.append('MISSING_NEGATIVE_PROBE')
            elif r.get('transport_errors') or r.get('probe_error'):
                reasons.append('INCONCLUSIVE_NEGATIVE_PROBE')
            elif r.get('success') is True:
                reasons.append('PROHIBITED_TLS_VERSION_ACCEPTED' if client=='tls12' else 'CLASSICAL_FALLBACK_ACCEPTED')
            elif not (r.get('success') is False and type(r.get('returncode')) is int
                      and r['returncode'] != 0 and r.get('ssl_error') == 1
                      and r.get('verify_result') == 0
                      and type(r.get('handshake_messages')) is int and r['handshake_messages'] > 0):
                reasons.append('INCONCLUSIVE_NEGATIVE_PROBE')
    # Compatibility requirements may add constraints, but cannot remove policy requirements.
    for client in q.get('required_clients', []):
        if not isinstance(probes.get(client), dict) or probes[client].get('success') is not True:
            reasons.append('REQUIRED_CLIENT_INCOMPATIBLE')
    return {'deployment_allowed': not reasons, 'reasons': list(dict.fromkeys(reasons)),
            'required_clients': policy['required_clients'], 'policy_version': policy['version']}
