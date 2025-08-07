#!/usr/bin/env python3

import subprocess
import sys
import time
import os
import getpass # For sensitive input
import tempfile # For creating temporary YAML files

# --- Helper Functions ---
def run_command(command, message="", exit_on_error=True):
    """
    Runs a shell command, prints messages, and optionally exits on error.
    Returns stdout on success, None on error if exit_on_error is False.
    """
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

def get_user_input(prompt, default="", sensitive=False):
    """
    Gets user input with an optional default value.
    Can hide input for sensitive information.
    """
    if sensitive:
        if default:
            return getpass.getpass(f"{prompt} (default: {default}): ") or default
        else:
            return getpass.getpass(f"{prompt}: ")
    else:
        if default:
            return input(f"{prompt} (default: {default}): ") or default
        else:
            return input(f"{prompt}: ")
            
# The apply_yaml_with_namespace_override function is now modified to also
# handle dynamic value injection within the ConfigMap/Job.
# We will create a new function for dynamic ConfigMap generation.


# --- Main Installation Logic ---

def main():
    """
    Main function for deploying the VWAP load generator.
    """
    print("\n--- Starting VWAP Load Generator setup ---")

    # Get namespace from command-line arguments (passed from vwap_setup.py -> voltsp_setup.py)
    if len(sys.argv) < 4: # Now expects voltsp_ns, redpanda_namespace, volt_ns
        print("Error: Missing arguments for namespaces.")
        print("Expected: vwap_loadgen_setup.py <loadgen_namespace> <redpanda_namespace> <volt_ns>")
        sys.exit(1)

    loadgen_ns = sys.argv[1] # This is typically the same as voltsp_ns
    redpanda_namespace = sys.argv[2]
    volt_ns = sys.argv[3] # VoltDB namespace

    print(f"Received Loadgen Namespace: '{loadgen_ns}'")
    print(f"Received Redpanda Namespace: '{redpanda_namespace}'")
    print(f"Received VoltDB Namespace: '{volt_ns}'")

    # Prerequisite check for yq (still needed if you decide to use it for job yaml, but we will make configmap dynamic)
    try:
        subprocess.run("yq --version", shell=True, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError:
        print("Error: 'yq' command not found. Please install yq to continue.")
        print("Installation instructions: https://github.com/mikefarah/yq#install")
        sys.exit(1)

    # We no longer ask for config file path as it's generated dynamically
    # default_config_path = os.path.join(script_dir, "yaml", "vwap-loadgen-config.yaml")
    # loadgen_config_path = get_user_input(f"Enter path to VWAP Loadgen Config YAML file", default=default_config_path)
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_job_path = os.path.join(script_dir, "yaml", "vwap-loadgen-job.yaml")
    loadgen_job_path = get_user_input(f"Enter path to VWAP Loadgen Job YAML file", default=default_job_path)

    # Check if local files exist before proceeding
    if not os.path.exists(loadgen_job_path):
        print(f"Error: Loadgen job file not found at {loadgen_job_path}")
        sys.exit(1)
    
    # --- Dynamically Generate VWAP Loadgen ConfigMap ---
    temp_config_file = None
    try:
        print("\n--- Dynamically Generating VWAP Loadgen ConfigMap ---")

        # Get Redpanda release name (assuming it's 'redpanda-cluster' as per previous logs)
        # This should ideally be passed from vwap_setup.py as an argument,
        # but for now, we'll hardcode the release name and use the passed namespace.
        red_panda_release_name = "redpanda-cluster"
        volt_cluster_name = "volt-vwap" # Assuming this is consistent from voltdb_core_setup.py

        # Construct dynamic addresses
        kafka_broker_addr = f"{red_panda_release_name}.{redpanda_namespace}.svc.cluster.local:9093"
        voltdb_svc_addr = f"{volt_cluster_name}-voltdb-cluster-client.{volt_ns}.svc.cluster.local:21212"

        print(f"  Setting KAFKA_BROKER_ADDR to: {kafka_broker_addr}")
        print(f"  Setting VOLTDB_SVC_ADDR to: {voltdb_svc_addr}")

        # Define the ConfigMap content as a multi-line string
        # Use f-strings for dynamic values
        vwap_loadgen_config_template = f"""
apiVersion: v1
kind: ConfigMap
metadata:
  name: vwap-loadgen-config
  namespace: {loadgen_ns} # This will be the actual namespace
data:
  VOLTDB_SVC_ADDR: "{voltdb_svc_addr}"
  KAFKA_BROKER_ADDR: "{kafka_broker_addr}"
  TOTAL_OPERATIONS: "2000000000"
  UNIQUE_TICKERS: "200"
  NUM_CLIENTS: "1"
"""
        # Write the dynamically generated content to a temporary file
        temp_config_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml')
        temp_config_path = temp_config_file.name
        temp_config_file.write(vwap_loadgen_config_template.strip())
        temp_config_file.close()

        run_command(f"kubectl apply -f {temp_config_path}", "Applying dynamically generated ConfigMap...", exit_on_error=True)
        print("Successfully deployed dynamically generated VWAP Loadgen ConfigMap.")

    finally:
        if temp_config_file and os.path.exists(temp_config_path):
            os.remove(temp_config_path)

    # --- Deploy Load Generator Job (namespace override only) ---
    print("\n--- Deploying Load Generator Job ---")
    
    # Use yq to override the namespace in the Job YAML and then apply it.
    temp_job_file = None
    try:
        yq_cmd = f"yq e '.metadata.namespace = \"{loadgen_ns}\"' {loadgen_job_path}"
        yq_output = run_command(yq_cmd, message=f"Overriding namespace in {os.path.basename(loadgen_job_path)} using yq...", exit_on_error=True)

        temp_job_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml')
        temp_job_path = temp_job_file.name
        temp_job_file.write(yq_output)
        temp_job_file.close()

        run_command(f"kubectl apply -f {temp_job_path}", "Applying Kubernetes Job manifest...", exit_on_error=True)
        print(f"Successfully applied '{os.path.basename(loadgen_job_path)}' to namespace '{loadgen_ns}'.")
    finally:
        if temp_job_file and os.path.exists(temp_job_path):
            os.remove(temp_job_path)

    print("\nVWAP Load Generator setup completed. You can monitor the job with:")
    print(f"  kubectl get jobs -n {loadgen_ns}")
    print(f"  kubectl get pods -l job-name=vwap-loadgen -n {loadgen_ns}")


if __name__ == "__main__":
    # The script should be called with three arguments now:
    # 1. loadgen_namespace (typically voltsp_ns)
    # 2. redpanda_namespace
    # 3. volt_ns (VoltDB namespace)
    # So we need to update the call in voltsp_setup.py
    main()
