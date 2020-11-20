##############################################################################
#
# Copyright (C) Zenoss, Inc. 2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""JSON Web Token (JWT)

Utilities for dealing with JWT.

"""

# Default Exports
__all__ = [
    "get_assertion",
    "json_encode",
    "prepare_key",
]

# stdlib Imports
import base64
import json
import re
import time

# Crypto Imports
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key


def b64encode(msg):
    return base64.urlsafe_b64encode(msg.rstrip('='))


def json_encode(data):
    return json.dumps(data, separators=(',', ':')).encode("utf-8")


def get_jwt_header(alg="RS256", typ="JWT"):
    return {"alg": alg, "typ": typ}


def get_jwt_claim_set(iss, scope, aud=None, exp=None, iat=None):
    if aud is None:
        aud = "https://www.googleapis.com/oauth2/v4/token"

    if exp is None or iat is None:
        now = int(time.time())

        if iat is None:
            iat = now

        if exp is None:
            exp = iat + 1800

    return {
        "iss": iss,
        "scope": scope,
        "aud": aud,
        "exp": exp,
        "iat": iat,
    }


def prepare_key(key):
    # Remove any doubly-escaped newlines
    key = key.decode("string_escape")
    # Remove any extra spaces from key body
    pem_regex = re.compile('(?P<prefix>-----BEGIN PRIVATE KEY-----)'  # Prefix
                           '(?P<key_body>[\w\s\+\/\n]+)'              # Key Body
                           '(?P<postfix>-----END PRIVATE KEY-----)'   # Postfix
                           '.*$')
    match = pem_regex.match(key)
    if match:
        key_body = match.group("key_body")
        key_body = re.sub(" ", "", key_body)
        # Re-constitute the key
        key = match.group("prefix") + key_body + match.group("postfix")

    return load_pem_private_key(key.encode("utf-8"), password=None, backend=default_backend())


def sign(msg, key):
    signer = key.signer(padding.PKCS1v15(), hashes.SHA256())
    signer.update(msg)
    return signer.finalize()


def get_assertion(iss, scope, key):
    header = get_jwt_header()
    payload = get_jwt_claim_set(iss, scope)

    segments = [
        b64encode(json_encode(header)),
        b64encode(json_encode(payload)),
    ]

    signing_input = b'.'.join(segments)
    key = prepare_key(key)
    signature = sign(signing_input, key)
    segments.append(b64encode(signature))

    return b'.'.join(segments)
