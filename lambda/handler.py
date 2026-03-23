import socket
import ssl
import json
import os
import urllib.request
import urllib.error
import boto3

REGION = os.environ.get("AWS_REGION", "eu-west-1")

ENDPOINTS = {
    "STS": f"sts.{REGION}.amazonaws.com",
    "SageMaker": f"api.sagemaker.{REGION}.amazonaws.com",
    "DataZone": f"datazone.{REGION}.amazonaws.com",
    "S3": f"s3.{REGION}.amazonaws.com",
}


def test_dns(results: dict) -> None:
    print("=" * 60)
    print("1. DNS RESOLUTION TEST")
    print("=" * 60)
    for name, host in ENDPOINTS.items():
        try:
            ip = socket.getaddrinfo(host, 443)[0][4][0]
            private = any(ip.startswith(p) for p in ["10.", "172.", "192.168."])
            status = "PRIVATE" if private else "PUBLIC - endpoint DNS broken"
            emoji = "✅" if private else "❌"
            print(f"{name:12} {ip:20} {emoji} {status}")
            results[name]["dns"] = {"ip": ip, "private": private, "status": status}
        except Exception as e:
            print(f"{name:12} FAILED - {e}")
            results[name]["dns"] = {"error": str(e)}


def test_tcp(results: dict) -> None:
    print()
    print("=" * 60)
    print("2. TCP CONNECTIVITY TEST (port 443)")
    print("=" * 60)
    for name, host in ENDPOINTS.items():
        try:
            sock = socket.create_connection((host, 443), timeout=5)
            sock.close()
            print(f"{name:12} ✅ TCP connection successful")
            results[name]["tcp"] = {"success": True}
        except socket.timeout:
            print(f"{name:12} ❌ TIMEOUT - route/SG blocking traffic")
            results[name]["tcp"] = {"success": False, "error": "timeout"}
        except Exception as e:
            print(f"{name:12} ❌ FAILED - {e}")
            results[name]["tcp"] = {"success": False, "error": str(e)}


def test_tls(results: dict) -> None:
    print()
    print("=" * 60)
    print("3. TLS HANDSHAKE TEST")
    print("=" * 60)
    for name, host in ENDPOINTS.items():
        try:
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(socket.socket(), server_hostname=host) as s:
                s.settimeout(5)
                s.connect((host, 443))
                cert = s.getpeercert()
                cn = cert["subject"][0][0][1]
                print(f"{name:12} ✅ TLS OK - cert CN: {cn}")
                results[name]["tls"] = {"success": True, "cn": cn}
        except Exception as e:
            print(f"{name:12} ❌ TLS FAILED - {e}")
            results[name]["tls"] = {"success": False, "error": str(e)}


def test_env() -> dict:
    print()
    print("=" * 60)
    print("4. ENVIRONMENT INFO")
    print("=" * 60)
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "unable to resolve"

    env_info = {
        "hostname": hostname,
        "local_ip": local_ip,
        "AWS_DEFAULT_REGION": os.environ.get("AWS_DEFAULT_REGION", "not set"),
        "AWS_EXECUTION_ENV": os.environ.get("AWS_EXECUTION_ENV", "not set"),
        "AWS_REGION": os.environ.get("AWS_REGION", "not set"),
    }
    for k, v in env_info.items():
        print(f"{k}: {v}")
    return env_info


def debug_https_endpoint(url: str) -> None:
    print()
    print("=" * 60)
    print("6. HTTPS ENDPOINT DEBUG")
    print(f"   {url}")
    print("=" * 60)

    # --- DNS ---
    from urllib.parse import urlparse
    parsed = urlparse(url)
    hostname = parsed.hostname
    port = parsed.port or 443
    try:
        ips = sorted({r[4][0] for r in socket.getaddrinfo(hostname, port)})
        print(f"DNS resolved to: {', '.join(ips)}")
    except Exception as e:
        print(f"DNS resolution FAILED: {e}")
        return

    # --- TCP ---
    try:
        sock = socket.create_connection((hostname, port), timeout=5)
        sock.close()
        print(f"TCP :{port}        ✅ connected")
    except Exception as e:
        print(f"TCP :{port}        ❌ FAILED - {e}")
        return

    # --- TLS ---
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=hostname) as s:
            s.settimeout(5)
            s.connect((hostname, port))
            cert = s.getpeercert()
            subject = dict(x[0] for x in cert.get("subject", []))
            issuer = dict(x[0] for x in cert.get("issuer", []))
            print(f"TLS               ✅ OK")
            print(f"  cert CN:         {subject.get('commonName', 'N/A')}")
            print(f"  cert issuer:     {issuer.get('organizationName', 'N/A')}")
            print(f"  cert notAfter:   {cert.get('notAfter', 'N/A')}")
    except Exception as e:
        print(f"TLS               ❌ FAILED - {e}")
        return

    # --- HTTP ---
    print()
    print("HTTP request:")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "vpc-endpoints-tester/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            reason = resp.reason
            headers = dict(resp.headers)
            body_bytes = resp.read(512)
            body_preview = body_bytes.decode("utf-8", errors="replace")
            print(f"  status:  {status} {reason}")
            print(f"  headers: {json.dumps(headers, indent=4)}")
            print(f"  body (first 512 bytes):\n{body_preview}")
    except urllib.error.HTTPError as e:
        print(f"  status:  {e.code} {e.reason}  ⚠️  (HTTP error, connection itself succeeded)")
        print(f"  headers: {json.dumps(dict(e.headers), indent=4)}")
        try:
            body_preview = e.read(512).decode("utf-8", errors="replace")
            print(f"  body (first 512 bytes):\n{body_preview}")
        except Exception:
            pass
    except Exception as e:
        print(f"  ❌ FAILED - {e}")


def get_caller_identity() -> None:
    print()
    print("=" * 60)
    print("7. CALLER IDENTITY (STS)")
    print("=" * 60)
    try:
        sts = boto3.client("sts", region_name=REGION)
        identity = sts.get_caller_identity()
        identity.pop("ResponseMetadata", None)
        print(json.dumps(identity, indent=2, default=str))
    except Exception as e:
        print(f"get_caller_identity FAILED: {e}")


def resolve_hostname(hostname: str) -> None:
    print()
    print("=" * 60)
    print("8. HOSTNAME RESOLUTION")
    print(f"   {hostname}")
    print("=" * 60)
    try:
        results = socket.getaddrinfo(hostname, None)
        ips = sorted({r[4][0] for r in results})
        for ip in ips:
            private = any(ip.startswith(p) for p in ["10.", "172.", "192.168."])
            status = "PRIVATE" if private else "PUBLIC"
            emoji = "✅" if private else "⚠️"
            print(f"  {ip:40} {emoji} {status}")
    except Exception as e:
        print(f"  FAILED - {e}")


def list_sagemaker_model_packages(model_package_group_arn: str = None) -> None:
    print()
    print("=" * 60)
    print("5. SAGEMAKER MODEL PACKAGE GROUPS & MODEL PACKAGES")
    if model_package_group_arn:
        print(f"   (using provided group ARN: {model_package_group_arn})")
    print("=" * 60)
    sm = boto3.client("sagemaker", region_name=REGION)

    try:
        if model_package_group_arn:
            groups = [{"ModelPackageGroupName": model_package_group_arn}]
            print(f"Using provided group ARN (skipping list)\n")
        else:
            paginator = sm.get_paginator("list_model_package_groups")
            groups = []
            for page in paginator.paginate():
                groups.extend(page.get("ModelPackageGroupSummaryList", []))
            print(f"Found {len(groups)} model package group(s)\n")

        for group in groups:
            group_name = group["ModelPackageGroupName"]
            print(f"--- Group: {group_name} ---")

            try:
                desc = sm.describe_model_package_group(ModelPackageGroupName=group_name)
                desc.pop("ResponseMetadata", None)
                print(json.dumps(desc, indent=2, default=str))
            except Exception as e:
                print(f"  describe_model_package_group FAILED: {e}")

            try:
                pkg_paginator = sm.get_paginator("list_model_packages")
                packages = []
                for page in pkg_paginator.paginate(ModelPackageGroupName=group_name):
                    packages.extend(page.get("ModelPackageSummaryList", []))

                print(f"  Model packages in '{group_name}': {len(packages)}")

                for pkg in packages:
                    pkg_arn = pkg["ModelPackageArn"]
                    pkg_version = pkg.get("ModelPackageVersion", "N/A")
                    print(f"\n  -- Package version {pkg_version} ({pkg_arn}) --")
                    try:
                        pkg_desc = sm.describe_model_package(ModelPackageName=pkg_arn)
                        pkg_desc.pop("ResponseMetadata", None)
                        print(json.dumps(pkg_desc, indent=4, default=str))
                    except Exception as e:
                        print(f"    describe_model_package FAILED: {e}")

            except Exception as e:
                print(f"  list_model_packages FAILED: {e}")

            print()

    except Exception as e:
        print(f"list_model_package_groups FAILED: {e}")


def lambda_handler(event, context):
    results = {name: {} for name in ENDPOINTS}

    test_dns(results)
    test_tcp(results)
    test_tls(results)
    env_info = test_env()
    get_caller_identity()

    if https_url := event.get("https_url"):
        debug_https_endpoint(https_url)

    list_sagemaker_model_packages(
        model_package_group_arn=event.get("model_package_group_arn")
    )

    if hostname := event.get("hostname"):
        resolve_hostname(hostname)

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "region": REGION,
                "endpoints_tested": list(ENDPOINTS.keys()),
                "results": results,
                "environment": env_info,
            },
            indent=2,
        ),
    }
