#!/usr/bin/env python3

import subprocess
import sys
import time
import os
import json
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

def check_kubernetes_secret_exists(secret_name, namespace):
    """
    Checks if a Kubernetes Secret exists in the given namespace.
    Returns True if it exists, False otherwise.
    """
    print(f"Checking if Kubernetes Secret '{secret_name}' exists in namespace '{namespace}'...")
    command = f"kubectl get secret {secret_name} -n {namespace} --ignore-not-found -o name"
    try:
        output = subprocess.run(command, shell=True, check=False, text=True, capture_output=True).stdout.strip()
        return output == f"secret/{secret_name}"
    except Exception as e:
        print(f"An error occurred while checking secret existence: {e}")
        return False

# --- Custom Waiting Functions (for VoltSP Deployment) ---

def wait_for_voltsp_deployment_ready(release_name, namespace, timeout_seconds=600):
    """
    Waits until the VoltSP Deployment is ready by polling.
    """
    start_time = time.time()
    print(f"Starting custom wait for VoltSP Deployment '{release_name}' in namespace '{namespace}' (timeout: {timeout_seconds}s)...")

    # The Deployment created by volt-streams is typically named <release-name>-volt-streams
    deployment_name = f"{release_name}-volt-streams"

    while time.time() - start_time < timeout_seconds:
        command = (
            f"kubectl get deployment {deployment_name} -n {namespace} "
            f"-o json"
        )
        try:
            result = subprocess.run(command, shell=True, check=True, text=True, capture_output=True)
            deploy_info = json.loads(result.stdout)

            ready_replicas = deploy_info.get('status', {}).get('readyReplicas', 0)
            desired_replicas = deploy_info.get('spec', {}).get('replicas', 0)

            if desired_replicas > 0 and ready_replicas == desired_replicas:
                print(f"VoltSP Deployment '{deployment_name}' is ready ({ready_replicas}/{desired_replicas} replicas).")
                return True
            else:
                print(f"  VoltSP Deployment '{deployment_name}' not yet ready ({ready_replicas}/{desired_replicas} replicas). Retrying in 10 seconds...")

        except subprocess.CalledProcessError as e:
            # Deployment might not exist yet or other kubectl error
            print(f"  Error checking deployment status: {e.stderr.strip()}. Retrying in 10 seconds...")
        except json.JSONDecodeError:
            print(f"  Failed to parse kubectl JSON output for Deployment. Retrying in 10 seconds...")
        except Exception as e:
            print(f"  An unexpected error occurred during Deployment check: {e}. Retrying in 10 seconds...")

        time.sleep(10)

    print(f"Timeout: VoltSP Deployment '{deployment_name}' did not become ready within {timeout_seconds} seconds.")
    return False

def create_namespace_if_not_exists(namespace_name):
    """
    Checks if a Kubernetes namespace exists and, if not, creates it.
    Uses 'kubectl apply' to handle both creation and pre-existence gracefully.
    """
    print(f"\nEnsuring namespace '{namespace_name}' exists...")
    # Use kubectl apply with a dry-run to create the namespace if it doesn't exist
    # This command is idempotent, so it won't fail if the namespace already exists.
    create_cmd = f"kubectl create namespace {namespace_name} --dry-run=client -o yaml | kubectl apply -f -"
    run_command(create_cmd, f"Creating or updating namespace '{namespace_name}'...")
    print(f"Namespace '{namespace_name}' is now ensured to exist.")
    return True

# --- Main Installation Logic (for VoltSP only) ---

def main():
    """
    Main function for the VoltSP setup script.
    """
    print("\n--- Starting VoltSP pipeline installation ---")

    # Arguments received from voltdb_core_setup.py
    if len(sys.argv) < 5:
        print("Error: Missing arguments for Redpanda and VoltDB details.")
        print("Expected: red_panda_release redpanda_namespace volt_cluster_name volt_ns")
        sys.exit(1)

    red_panda_release = sys.argv[1]
    redpanda_namespace = sys.argv[2]
    volt_cluster_name = sys.argv[3]
    volt_ns = sys.argv[4]

    print(f"Received Redpanda details: Release='{red_panda_release}', Namespace='{redpanda_namespace}'")
    print(f"Received VoltDB details: Cluster='{volt_cluster_name}', Namespace='{volt_ns}'")

    pipeline_name = get_user_input("Enter the VoltSP Pipeline Name", default="pipeline1")
    voltsp_ns = get_user_input("Enter Namespace to install VoltSP", default=volt_ns)
    
    # Check for and create the namespace if it doesn't exist
    create_namespace_if_not_exists(voltsp_ns)
    
    # --- Docker Registry Secret ---
    print("\n--- Docker Registry Credentials (for VoltSP images) ---")
    create_secret = get_user_input("Do you need to create/update a Docker registry secret for VoltSP? (yes/no)", default="yes")

    docker_secret_name = "voltsp-docker-registry-secret" # Default secret name for VoltSP
    
    if create_secret.lower() == "yes":
        if check_kubernetes_secret_exists(docker_secret_name, voltsp_ns):
            print(f"Kubernetes Secret '{docker_secret_name}' already exists in namespace '{voltsp_ns}'. Skipping creation.")
            # Option to re-create/update could be added here if desired.
        else:
            print(f"Creating Kubernetes Secret '{docker_secret_name}' in namespace '{voltsp_ns}'.")
            docker_server = "docker.io" # Hardcoded to docker.io as per request
            docker_username = get_user_input("Enter Docker Username")
            docker_password = get_user_input("Enter Docker Password", sensitive=True)
            docker_email = get_user_input("Enter Docker Email (optional)", default="")

            create_secret_cmd = (
                f"kubectl create secret docker-registry {docker_secret_name} "
                f"--docker-server={docker_server} "
                f"--docker-username={docker_username} "
                f"--docker-password={docker_password} "
                f"{f'--docker-email={docker_email}' if docker_email else ''} "
                f"-n {voltsp_ns}"
            )
            run_command(create_secret_cmd, "Creating Docker registry secret...")
            print(f"Docker registry secret '{docker_secret_name}' created successfully in namespace '{voltsp_ns}'.")
    else:
        print("Skipping Docker registry secret creation.")

    # Use the same license file as for VoltDB core
    default_license_path = "/Users/gulshansharma/Desktop/VoltActiveDataGulshan_Enterprise_XDCR_Expires-2026-02-15.xml"
    license_xml_path = get_user_input(f"Enter path to VoltSP license XML file", default=default_license_path)

    default_jar_path = "/Users/gulshansharma/Downloads/voltsptest1/volt-vwap/target/vwap-demo-1.0-SNAPSHOT-voltsp-kafka-reader-stream.jar"
    voltsp_jar_path = get_user_input(f"Enter path to VoltSP Kafka Reader Stream JAR file", default=default_jar_path)

    # Note: vwap-demo-1.0-SNAPSHOT-voltsp-kafka-reader-stream.jar requires configuration in voltsp.yaml
    # to connect to Redpanda. Ensure voltsp.yaml is correctly configured with Redpanda broker addresses.
    default_yaml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voltsp.yaml")
    voltsp_yaml_path = get_user_input(f"Enter path to the VoltSP YAML configuration file", default=default_yaml_path)


    # Check if local files exist before proceeding
    if not os.path.exists(license_xml_path):
        print(f"Error: VoltSP license file not found at {license_xml_path}")
        sys.exit(1)
    if not os.path.exists(voltsp_jar_path):
        print(f"Error: VoltSP JAR file not found at {voltsp_jar_path}")
        sys.exit(1)
    if not os.path.exists(voltsp_yaml_path):
        print(f"Error: VoltSP YAML file not found at {voltsp_yaml_path}")
        sys.exit(1)


    try:
        # --- Check if Helm release already exists (Automatic Skip) ---
        helm_status_cmd = f"helm status {pipeline_name} -n {voltsp_ns}"
        helm_release_exists = False
        try:
            subprocess.run(helm_status_cmd, shell=True, check=True, text=True, capture_output=True)
            helm_release_exists = True
        except subprocess.CalledProcessError:
            helm_release_exists = False

        if helm_release_exists:
            print(f"\nVoltSP Helm release '{pipeline_name}' already exists in namespace '{voltsp_ns}'. Skipping installation.")
        else:
            print(f"\nVoltSP Helm release '{pipeline_name}' does not exist. Proceeding with new installation.")
            install_voltsp_cmd = (
                f"helm install {pipeline_name} voltdb/volt-streams "
                f"--set-file streaming.licenseXMLFile={license_xml_path} "
                f"--set-file streaming.voltapps={voltsp_jar_path} "
                f"--values {voltsp_yaml_path} "
                f"--set imagePullSecrets[0].name={docker_secret_name} " # Add imagePullSecrets if secret was created/should be used
                f"-n {voltsp_ns}"
            )
            run_command(install_voltsp_cmd, "Installing VoltSP pipeline...")

        # --- WAITING LOGIC FOR VOLTSP DEPLOYMENT ---
        if not wait_for_voltsp_deployment_ready(pipeline_name, voltsp_ns):
            print("VoltSP pipeline did not become ready within the timeout. Please check cluster status manually.")
            sys.exit(1)

        print("VoltSP pipeline is ready.")
        print("VoltSP installation complete.")

    finally:
        pass  # No cleanup is needed as files are user-provided


    # --- Call the VWAP App setup script ---
    print("\n--- Starting VWAP Load Generator setup script... ---")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    vwap_loadgen_script_path = os.path.join(script_dir, "vwap_loadgen_setup.py")

    try:
        # Correctly pass the namespace to the load generator script
        subprocess.run([sys.executable, vwap_loadgen_script_path, voltsp_ns], check=True)
        print("\nVWAP Load Generator setup completed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"\nVWAP Load Generator setup failed: {e}")
        print(f"Stderr from vwap_loadgen_setup.py: {e.stderr}")
        print(f"Stdout from vwap_loadgen_setup.py: {e.stdout}")
        sys.exit(1)


if __name__ == "__main__":
    main()
