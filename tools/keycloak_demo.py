"""Start the isolated, localhost-only Keycloak pilot. No default passwords."""

import argparse
import fcntl
import json
import os
import secrets
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import uvicorn

from aegisflow.access import SourceAccess, SourceGrant, SourcePolicy
from aegisflow.api import create_app
from aegisflow.contracts import Scope
from aegisflow.identity import (
    IdentityPolicy,
    IdentityUnavailable,
    JWTIdentity,
    PrincipalBinding,
    load_json,
)
from aegisflow.oidc import BrowserLogin, LocalKeycloak, ProviderKeys
from aegisflow.pilot_scenarios import pilot_scenarios
from aegisflow.scenario import generate
from aegisflow.store import Store

IMAGE = "quay.io/keycloak/keycloak@sha256:3f3c5f8e03c614774b4bd9173b88391fefa4153bfc010d8012d59ad825377332"
CONTAINER = "aegisflow-local-keycloak"
VOLUME = "aegisflow-local-keycloak-import"
DIRECTORY = Path("work/keycloak-local")
ISSUER = "http://127.0.0.1:8080/realms/aegisflow-local"
CLIENT = "aegisflow-local-browser"
CALLBACK = "http://127.0.0.1:8000/auth/callback"


def docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def write_private(path, content):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        stream.write(content)
    temporary.replace(path)


def prepare():
    DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (DIRECTORY / "realm.json").exists():
        if not all((DIRECTORY / name).exists() for name in ("login.json", "login.txt")):
            raise RuntimeError("Incomplete local setup; existing files were preserved")
        return
    password, subject = secrets.token_urlsafe(24), str(uuid4())
    realm = {
        "realm": "aegisflow-local",
        "enabled": True,
        "sslRequired": "none",
        "registrationAllowed": False,
        "resetPasswordAllowed": False,
        "rememberMe": False,
        "bruteForceProtected": True,
        "accessTokenLifespan": 600,
        "ssoSessionIdleTimeout": 900,
        "ssoSessionMaxLifespan": 1800,
        "clients": [
            {
                "clientId": CLIENT,
                "enabled": True,
                "publicClient": True,
                "standardFlowEnabled": True,
                "directAccessGrantsEnabled": False,
                "implicitFlowEnabled": False,
                "serviceAccountsEnabled": False,
                "redirectUris": [CALLBACK],
                "webOrigins": ["http://127.0.0.1:8000"],
                "attributes": {
                    "pkce.code.challenge.method": "S256",
                    "post.logout.redirect.uris": "http://127.0.0.1:8000/",
                },
                "protocolMappers": [
                    {
                        "name": "aegisflow-api-audience",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-audience-mapper",
                        "config": {
                            "included.custom.audience": "aegisflow-api",
                            "access.token.claim": "true",
                            "id.token.claim": "false",
                        },
                    }
                ],
            }
        ],
        "users": [
            {
                "id": subject,
                "username": "analyst",
                "enabled": True,
                "emailVerified": True,
                "firstName": "Demo",
                "lastName": "Analyst",
                "email": "analyst@example.invalid",
                "requiredActions": [],
                "credentials": [{"type": "password", "value": password, "temporary": False}],
            }
        ],
    }
    write_private(DIRECTORY / "realm.json", json.dumps(realm))
    write_private(
        DIRECTORY / "login.json",
        json.dumps({"username": "analyst", "password": password, "subject": subject}),
    )
    write_private(
        DIRECTORY / "login.txt",
        "AegisFlow LOCAL TEST ACCOUNT\nUsername: analyst\nPassword: "
        + password
        + "\nDo not share this file. Synthetic local use only.\n",
    )


def start_provider():
    existing = docker(
        "inspect",
        CONTAINER,
        "--format",
        '{{index .Config.Labels "org.aegisflow.purpose"}}',
        check=False,
    )
    if existing.returncode == 0:
        if existing.stdout.strip() != "local-oidc":
            raise RuntimeError("Container name belongs to another setup; nothing was changed")
        actual_image = docker("inspect", CONTAINER, "--format", "{{.Config.Image}}").stdout.strip()
        if actual_image != IMAGE:
            raise RuntimeError("Existing local container uses a different image; not replaced")
        verify_ports()
        docker("start", CONTAINER)
    else:
        if docker("image", "inspect", IMAGE, check=False).returncode != 0:
            print("Downloading pinned Keycloak 26.8.1 image...", flush=True)
            docker("pull", IMAGE)
        volume = docker(
            "volume",
            "inspect",
            VOLUME,
            "--format",
            '{{index .Labels "org.aegisflow.purpose"}}',
            check=False,
        )
        if volume.returncode == 0 and volume.stdout.strip() != "local-oidc":
            raise RuntimeError("Import volume belongs to another setup")
        docker("volume", "create", "--label", "org.aegisflow.purpose=local-oidc", VOLUME)
        docker(
            "run",
            "--rm",
            "--user",
            "0:0",
            "--entrypoint",
            "/bin/sh",
            "--mount",
            f"type=bind,src={(DIRECTORY / 'realm.json').resolve()},dst=/run/realm.json,readonly",
            "--mount",
            f"type=volume,src={VOLUME},dst=/import",
            IMAGE,
            "-c",
            "cp /run/realm.json /import/aegisflow-local-realm.json && chown 1000:0 /import/aegisflow-local-realm.json && chmod 400 /import/aegisflow-local-realm.json",
        )
        docker(
            "run",
            "--detach",
            "--name",
            CONTAINER,
            "--label",
            "org.aegisflow.purpose=local-oidc",
            "--publish",
            "127.0.0.1:8080:8080",
            "--mount",
            f"type=volume,src={VOLUME},dst=/opt/keycloak/data/import,readonly",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            "1g",
            "--cpus",
            "2",
            "--pids-limit",
            "256",
            IMAGE,
            "start-dev",
            "--import-realm",
            "--hostname=http://127.0.0.1:8080",
        )
    verify_ports()


def verify_ports():
    ports = json.loads(
        docker("inspect", CONTAINER, "--format", "{{json .HostConfig.PortBindings}}").stdout
    )
    if ports != {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]}:
        raise RuntimeError("Unexpected provider port binding; startup refused")


def make_app():
    provider = LocalKeycloak(ISSUER, CLIENT, CALLBACK)
    for _ in range(120):
        try:
            discovery = provider.fetch("/.well-known/openid-configuration")
            break
        except IdentityUnavailable:
            time.sleep(0.5)
    else:
        raise RuntimeError("Keycloak did not become ready; no identity fallback used")
    if (
        discovery.get("issuer") != ISSUER
        or discovery.get("token_endpoint") != ISSUER + "/protocol/openid-connect/token"
    ):
        raise RuntimeError("Unexpected local provider metadata")
    account = json.loads((DIRECTORY / "login.json").read_text())
    scope = Scope(tenant_id="demo", subject_id="local-demo", permissions={"read", "investigate"})
    # Preserve operator revocations on restart; provision only missing policies.
    if not (DIRECTORY / "principals.json").exists():
        write_private(
            DIRECTORY / "principals.json",
            IdentityPolicy(
                revision="local-1",
                principals=(PrincipalBinding(external_subject=account["subject"], scope=scope),),
            ).model_dump_json(indent=2),
        )
    if not (DIRECTORY / "source-acl.json").exists():
        write_private(
            DIRECTORY / "source-acl.json",
            SourcePolicy(
                revision="local-1",
                grants=(
                    SourceGrant(
                        tenant_id=scope.tenant_id,
                        subject_id=scope.subject_id,
                        source_uris=generate().input_source_uris(),
                    ),
                ),
            ).model_dump_json(indent=2),
        )
    identity = JWTIdentity(
        ISSUER,
        "aegisflow-api",
        None,
        DIRECTORY / "principals.json",
        profile="keycloak",
        client_id=CLIENT,
        key_source=ProviderKeys(provider),
    )
    return create_app(
        Store(DIRECTORY / "cases.db"),
        {},
        pilot_scenarios(),
        source_access=SourceAccess(DIRECTORY / "source-acl.json"),
        identity=identity,
        browser_login=BrowserLogin(identity, provider),
    )


def revoke_sessions():
    """Trusted local operator command; preserve account, grants and prior cutoffs."""
    with os.fdopen(
        os.open(DIRECTORY / "operator.lock", os.O_WRONLY | os.O_CREAT, 0o600), "w"
    ) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        account = json.loads((DIRECTORY / "login.json").read_text())
        policy_file = DIRECTORY / "principals.json"
        policy = IdentityPolicy.model_validate_json(load_json(policy_file))
        matches = [p for p in policy.principals if p.external_subject == account["subject"]]
        if len(matches) != 1:
            raise RuntimeError("Local principal missing; policy was not changed")
        cutoff = max(int(time.time()), matches[0].tokens_valid_after)
        bindings = tuple(
            p.model_copy(update={"tokens_valid_after": cutoff}) if p == matches[0] else p
            for p in policy.principals
        )
        updated = policy.model_copy(
            update={"revision": "local-revoke-" + uuid4().hex, "principals": bindings}
        )
        payload = updated.model_dump_json(indent=2)
        if len(payload.encode()) > 65536:
            raise ValueError("Updated identity policy would exceed the verifier limit")
        write_private(policy_file, payload)
    print(
        "Existing local AegisFlow tokens revoked. Sign in again after this UTC second. Keycloak SSO is unchanged."
    )


def enable_synthetic_actions():
    """Explicit local operator opt-in; never changes other principals or revocations."""
    with os.fdopen(
        os.open(DIRECTORY / "operator.lock", os.O_WRONLY | os.O_CREAT, 0o600), "w"
    ) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        account = json.loads((DIRECTORY / "login.json").read_text())
        file = DIRECTORY / "principals.json"
        policy = IdentityPolicy.model_validate_json(load_json(file))
        matches = [p for p in policy.principals if p.external_subject == account["subject"]]
        if len(matches) != 1 or matches[0].scope.tenant_id != "demo":
            raise RuntimeError("Expected local demo principal missing")
        original = matches[0]
        updated_scope = original.scope.model_copy(
            update={"permissions": original.scope.permissions | {"approve", "execute"}}
        )
        bindings = tuple(
            p.model_copy(update={"scope": updated_scope}) if p == original else p
            for p in policy.principals
        )
        write_private(
            file,
            policy.model_copy(
                update={"revision": "local-actions-" + uuid4().hex, "principals": bindings}
            ).model_dump_json(indent=2),
        )
    print("Synthetic action approval/execution enabled for the local demo principal.")


def main():
    parser = argparse.ArgumentParser(
        description="Local browser login with isolated Keycloak; synthetic use only"
    )
    parser.add_argument(
        "command",
        choices=["start", "stop", "revoke-sessions", "enable-synthetic-actions"],
        nargs="?",
        default="start",
    )
    args = parser.parse_args()
    if args.command == "enable-synthetic-actions":
        enable_synthetic_actions()
        return
    if args.command == "revoke-sessions":
        revoke_sessions()
        return
    if args.command == "stop":
        owner = docker(
            "inspect", CONTAINER, "--format", '{{index .Config.Labels "org.aegisflow.purpose"}}'
        ).stdout.strip()
        if owner != "local-oidc":
            raise RuntimeError("Container ownership mismatch")
        docker("stop", CONTAINER)
        print(
            "Local Keycloak stopped. Stop the foreground API terminal with Ctrl+C if still running."
        )
        return
    prepare()
    print(
        "Starting local Keycloak. No default password; credentials stay in work/keycloak-local/login.txt.",
        flush=True,
    )
    start_provider()
    try:
        app = make_app()
        print(
            "Open http://127.0.0.1:8000 . Username: analyst. Read the password locally: open work/keycloak-local/login.txt",
            flush=True,
        )
        uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False)
    finally:
        docker("stop", CONTAINER, check=False)


if __name__ == "__main__":
    main()
