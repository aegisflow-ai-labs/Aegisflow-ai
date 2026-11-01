"""One-command localhost demo; disposable signing key stays in memory only."""

import argparse
import json
import os
import secrets
import shlex
from datetime import UTC, datetime
from pathlib import Path

import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa

from aegisflow.access import SourceAccess, SourceGrant, SourcePolicy
from aegisflow.api import create_app
from aegisflow.contracts import Scope
from aegisflow.identity import IdentityPolicy, JWTIdentity, PrincipalBinding
from aegisflow.scenario import generate
from aegisflow.store import Store

ISSUER = "https://aegisflow.invalid/local-demo"
AUDIENCE = "aegisflow-api"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Disposable JWT verification demo; not an OIDC login server"
    )
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--setup-only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    directory = args.directory or Path("work") / f"jwt-demo-{secrets.token_hex(4)}"
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    scope = Scope(tenant_id="demo", subject_id="local-demo", permissions={"read", "investigate"})
    source = generate()
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = {
        **jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key(), as_dict=True),
        "kid": "demo-1",
        "alg": "RS256",
        "use": "sig",
    }
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "demo-user",
            "iat": now,
            "nbf": now,
            "exp": now + 600,
            "client_id": "local-demo",
            "jti": secrets.token_hex(16),
        },
        private,
        algorithm="RS256",
        headers={"kid": "demo-1", "typ": "at+jwt"},
    )
    del private
    files = {
        "jwks.json": json.dumps({"keys": [jwk]}),
        "principals.json": IdentityPolicy(
            revision="demo-1",
            principals=(PrincipalBinding(external_subject="demo-user", scope=scope),),
        ).model_dump_json(indent=2),
        "source-acl.json": SourcePolicy(
            revision="demo-1",
            grants=(
                SourceGrant(
                    tenant_id=scope.tenant_id,
                    subject_id=scope.subject_id,
                    source_uris=source.input_source_uris(),
                ),
            ),
        ).model_dump_json(indent=2),
        "headers.txt": f"Authorization: Bearer {token}\nContent-Type: application/json\n",
    }
    for name, content in files.items():
        with os.fdopen(
            os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as file:
            file.write(content)
    print(
        f"Local demo files: {directory}. Access token expires in 10 minutes. Signing key is not saved.",
        flush=True,
    )
    print("Run in another terminal from the same directory:", flush=True)
    print(
        f'curl --fail-with-body http://127.0.0.1:{args.port}/v1/cases --header @{shlex.quote(str(directory / "headers.txt"))} --header \'Idempotency-Key: jwt-demo-001\' --data \'{{"order_id":"PO-001","as_of":"2026-11-01T18:00:00Z"}}\'',
        flush=True,
    )
    if args.setup_only:
        return
    identity = JWTIdentity(ISSUER, AUDIENCE, directory / "jwks.json", directory / "principals.json")
    app = create_app(
        Store(directory / "cases.db"),
        {},
        (source,),
        source_access=SourceAccess(directory / "source-acl.json"),
        identity=identity,
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
