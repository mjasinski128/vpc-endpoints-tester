import socket
import ssl
import json
import os
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
    list_sagemaker_model_packages(
        model_package_group_arn=event.get("model_package_group_arn")
    )

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
