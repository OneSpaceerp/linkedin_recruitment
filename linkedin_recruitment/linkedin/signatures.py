"""LinkedIn webhook security: endpoint validation challenge and push-event signatures.

Challenge (GET ?challengeCode=...):
    challengeResponse = hex(HMAC-SHA256(key=clientSecret, msg=challengeCode))

Push event (POST, header X-LI-Signature):
    X-LI-Signature = hex(HMAC-SHA256(key=clientSecret, msg="hmacsha256=" + raw body))

The Apply Connect page also describes the header as carrying the ``hmacsha256=`` prefix, so
both forms of the header are accepted. The raw body must be used exactly as received.
"""

import hashlib
import hmac

PREFIX = "hmacsha256="


def _hex(secret, message):
    if isinstance(secret, str):
        secret = secret.encode()
    if isinstance(message, str):
        message = message.encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def challenge_response(challenge_code, client_secret):
    return _hex(client_secret, challenge_code or "")


def challenge_body(challenge_code, client_secret):
    return {"challengeCode": challenge_code, "challengeResponse": challenge_response(challenge_code, client_secret)}


def expected_signature(raw_body, client_secret):
    body = raw_body if isinstance(raw_body, bytes) else (raw_body or "").encode()
    return _hex(client_secret, PREFIX.encode() + body)


def verify_signature(raw_body, header, client_secret):
    """True when ``header`` is LinkedIn's signature of ``raw_body``. Constant-time compare."""
    if not header or not client_secret:
        return False
    received = header.strip()
    if received.lower().startswith(PREFIX):
        received = received[len(PREFIX):]
    return hmac.compare_digest(received.lower(), expected_signature(raw_body, client_secret))


def verify_any(raw_body, header, secrets):
    """Several client secrets (parent and child apps, or a rotated secret): True if any matches."""
    return any(verify_signature(raw_body, header, s) for s in secrets if s)
