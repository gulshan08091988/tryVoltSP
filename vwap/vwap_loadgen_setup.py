#!/usr/bin/env python3

import subprocess
import sys
import os
import tempfile

def run_command(command, message="", exit_on_error=True):
    """Run a shell command with optional message and error handling."""
    if message:
        print(message)
    try:
        process = subprocess.run(command, shell=True, check=True, text=True, capture_output=True)
        if process.stdout:
            print(process.stdout)
        return process.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {command}")
        print(f"Stdout: {e.stdout}")
        print(f"Stderr: {e.stderr}")
        if exit_on_error:
            sys.exit(1)
        return None

def get_user_input(prompt, default=""):
    """Prompt user for input with a default value."""
    user_input = input(f"{prompt} (default: {default}): ")
    return user_input.strip() or default

def namespace_exists(ns):
    """Check if a Kubernetes namespace exists."""
    result = subprocess.run(f"kubectl get ns {ns}", shell=True, text=True, capture_output=True)
    return result.returncode == 0

def create_namespace(ns):
    """Create a Kubernetes namespace if it doesn't exist."""
    if not namespace_exists(ns):
        print(f"Namespace '{ns}' does not exist. Creating...")
        run_command(f"kubectl create ns {ns}", exit_on_error=True)
    else:
        print(f"Namespace '{ns}' already exists.")

def find_namespace_by_service(service_name_pattern):
    """Find namespace of a service by name pattern."""
    cmd = (
        f"kubectl get svc --all-namespaces "
        f"-o jsonpath='{{range .items[?(@.metadata.name==\"{service_name_pattern}\")]}}"
        f"{{.metadata.namespace}}{{\"\\n\"}}{{end}}'"
    )
    result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    ns = result.stdout.strip()
    if not ns:
        print(f"Error: Could not find namespace for service '{service_name_pattern}'")
        sys.exit(1)
    return ns

def main():
    print("\n--- Starting VWAP Load Generator setup ---")

    # Ask user only for Loadgen namespace
    loadgen_ns = get_user_input("Enter namespace to install Loadgen job", default="voltsp")

    # Dynamically detect Redpanda and VoltDB namespaces
    redpanda_namespace = find_namespace_by_service("redpanda-cluster")
    volt_ns = find_namespace_by_service("volt-vwap-voltdb-cluster-client")

    print(f"Loadgen Namespace: {loadgen_ns}")
    print(f"Redpanda Namespace: {redpanda_namespace}")
    print(f"VoltDB Namespace: {volt_ns}")

    # Ensure namespace exists
    create_namespace(loadgen_ns)

    # Check for yq installation
    try:
        subprocess.run("yq --version", shell=True, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError:
        print("Error: 'yq' not found. Install from https://github.com/mikefarah/yq#install")
        sys.exit(1)

    # Paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    yaml_dir = os.path.join(script_dir, "yaml")
    os.makedirs(yaml_dir, exist_ok=True)

    default_job_path = os.path.join(yaml_dir, "vwap-loadgen-job.yaml")
    loadgen_job_path = get_user_input("Enter path to VWAP Loadgen Job YAML file", default=default_job_path)

    if not os.path.exists(loadgen_job_path):
        print(f"Error: Loadgen job file not found at {loadgen_job_path}")
        sys.exit(1)

    # Default config values
    total_ops = "2000000000"
    unique_tickers = "200"
    num_clients = "1"
    tps = "2"
    skip_something = "0"

    # Build service addresses dynamically
    red_panda_release_name = "redpanda-cluster"
    volt_cluster_name = "volt-vwap"
    kafka_broker_addr = f"{red_panda_release_name}.{redpanda_namespace}.svc.cluster.local:9093"
    voltdb_svc_addr = f"{volt_cluster_name}-voltdb-cluster-client.{volt_ns}.svc.cluster.local:21212"

    # Generate ConfigMap YAML
    config_file_path = os.path.join(yaml_dir, "vwap-loadgen-config.yaml")
    vwap_loadgen_config_content = f"""
apiVersion: v1
kind: ConfigMap
metadata:
  name: vwap-loadgen-config
  namespace: {loadgen_ns}
data:
  VOLTDB_SVC_ADDR: "{voltdb_svc_addr}"
  KAFKA_BROKER_ADDR: "{kafka_broker_addr}"
  TOTAL_OPERATIONS: "{total_ops}"
  UNIQUE_TICKERS: "{unique_tickers}"
  NUM_CLIENTS: "{num_clients}"
  TPS: "{tps}"
  SKIP_SOMETHING: "{skip_something}"
"""

    print("\n--- ConfigMap content to be written ---")
    print(vwap_loadgen_config_content.strip())

    with open(config_file_path, "w") as f:
        f.write(vwap_loadgen_config_content.strip() + "\n")
    print(f"Saved ConfigMap to {config_file_path}")

    # Apply ConfigMap
    run_command(f"kubectl apply -f {config_file_path}", "Applying ConfigMap...", exit_on_error=True)
    print("ConfigMap applied successfully.")

    # Deploy Job (override namespace only)
    print("\n--- Deploying Load Generator Job ---")
    temp_job_file = None
    try:
        yq_cmd = f"yq e '.metadata.namespace = \"{loadgen_ns}\"' {loadgen_job_path}"
        yq_output = run_command(yq_cmd, "Overriding namespace in Job YAML...", exit_on_error=True)

        temp_job_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml')
        temp_job_path = temp_job_file.name
        temp_job_file.write(yq_output)
        temp_job_file.close()

        run_command(f"kubectl apply -f {temp_job_path}", "Applying Job manifest...", exit_on_error=True)
        print(f"Job applied successfully to namespace '{loadgen_ns}'.")
    finally:
        if temp_job_file and os.path.exists(temp_job_path):
            os.remove(temp_job_path)

    print("\nVWAP Load Generator setup completed.")
    print(f"Check job: kubectl get jobs -n {loadgen_ns}")
    print(f"Check pods: kubectl get pods -l job-name=vwap-loadgen -n {loadgen_ns}")

if __name__ == "__main__":
    main()

