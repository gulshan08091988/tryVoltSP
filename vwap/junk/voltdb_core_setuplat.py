#!/usr/bin/env python3

import subprocess
import sys
import time
import os
import json
import getpass # For sensitive input
import tempfile # For creating temporary YAML files

# --- Helper Functions ---
def run_command(command, message="", exit_on_error=True, suppress_stdout=False):
    """
    Runs a shell command, prints messages, and optionally exits on error.
    Returns stdout on success, None on error if exit_on_error is False.
    'suppress_stdout' will redirect stdout to DEVNULL, useful for noisy but successful commands.
    """
    if message:
        print(message)
    try:
        if suppress_stdout:
            process = subprocess.run(command, shell=True, check=True, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if process.stderr: # Still print stderr if there's an issue even when suppressing stdout
                print(process.stderr)
            return process.stdout # This will be empty due to DEVNULL, but return type consistent
        else:
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

def create_namespace_if_not_exists(namespace_name):
    """
    Checks if a Kubernetes namespace exists and, if not, creates it.
    Uses 'kubectl apply' to handle both creation and pre-existence gracefully.
    """
    print(f"\nEnsuring namespace '{namespace_name}' exists...")
    create_cmd = f"kubectl create namespace {namespace_name} --dry-run=client -o yaml | kubectl apply -f -"
    run_command(create_cmd, f"Creating or updating namespace '{namespace_name}'...")
    print(f"Namespace '{namespace_name}' is now ensured to exist.")
    return True

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

def get_voltdb_statefulset_name(release_name):
    """
    Derives the expected StatefulSet name for a VoltDB cluster based on the Helm release name.
    Based on helm get manifest, the VoltDBCluster CR and subsequent StatefulSet are named:
    $(RELEASE_NAME)-voltdb-cluster
    """
    return f"{release_name}-voltdb-cluster"

def check_statefulset_exists_and_ready(release_name, namespace):
    """
    Checks if a Kubernetes StatefulSet (for VoltDB) exists and has any ready replicas.
    Returns True if exists and ready replicas > 0, False otherwise.
    """
    statefulset_name = get_voltdb_statefulset_name(release_name)
    print(f"Checking Kubernetes StatefulSet '{statefulset_name}' in namespace '{namespace}'...")
    command = f"kubectl get statefulset {statefulset_name} -n {namespace} -o json"
    try:
        result = subprocess.run(command, shell=True, check=True, text=True, capture_output=True)
        sts_info = json.loads(result.stdout)
        ready_replicas = sts_info.get('status', {}).get('readyReplicas', 0)
        desired_replicas = sts_info.get('spec', {}).get('replicas', 0)

        if desired_replicas > 0 and ready_replicas == desired_replicas:
            print(f"StatefulSet '{statefulset_name}' is fully ready ({ready_replicas}/{desired_replicas} replicas).")
            return True
        elif ready_replicas > 0:
            print(f"StatefulSet '{statefulset_name}' exists but is not fully ready ({ready_replicas}/{desired_replicas} replicas).")
            return True # Exists, but not fully ready, so we might want to wait
        else:
            print(f"StatefulSet '{statefulset_name}' exists but has no ready replicas ({ready_replicas}/{desired_replicas} replicas).")
            return False # Exists, but seems stuck or not started
    except subprocess.CalledProcessError as e:
        if "NotFound" in e.stderr: # This check is valid when capture_output=True
            print(f"StatefulSet '{statefulset_name}' not found in namespace '{namespace}'.")
        else:
            print(f"Error checking StatefulSet status: {e.stderr.strip()}")
        return False
    except json.JSONDecodeError:
        print(f"Failed to parse kubectl JSON output for StatefulSet '{statefulset_name}'.")
        return False
    except Exception as e:
        print(f"An unexpected error occurred during StatefulSet check: {e}")
        return False

def wait_for_statefulset_object_to_exist(statefulset_name, namespace, timeout_seconds=120):
    """
    Polls until the StatefulSet Kubernetes object exists.
    """
    start_time = time.time()
    print(f"Waiting for StatefulSet object '{statefulset_name}' to exist in namespace '{namespace}' (timeout: {timeout_seconds}s)...")
    while time.time() - start_time < timeout_seconds:
        command = f"kubectl get statefulset {statefulset_name} -n {namespace} --ignore-not-found -o name"
        result = subprocess.run(command, shell=True, text=True, capture_output=True, check=False)
        # Check for both "statefulset/<name>" and "statefulset.apps/<name>" formats
        if result.stdout.strip() == f"statefulset/{statefulset_name}" or \
           result.stdout.strip() == f"statefulset.apps/{statefulset_name}":
            print(f"StatefulSet '{statefulset_name}' object found.")
            return True
        else:
            print(f"  StatefulSet '{statefulset_name}' object not yet found. Retrying in 5 seconds...")
            time.sleep(5)
    print(f"Timeout: StatefulSet object '{statefulset_name}' did not appear within {timeout_seconds} seconds.")
    return False


def wait_for_voltdb_cluster_ready(release_name, namespace, timeout_seconds=900):
    """
    Waits until the VoltDB StatefulSet is ready by polling.
    """
    statefulset_name = get_voltdb_statefulset_name(release_name)
    start_time = time.time()
    print(f"Starting custom wait for VoltDB StatefulSet '{statefulset_name}' in namespace '{namespace}' (timeout: {timeout_seconds}s)...")

    while time.time() - start_time < timeout_seconds:
        command = (
            f"kubectl get statefulset {statefulset_name} -n {namespace} "
            f"-o json"
        )
        try:
            result = subprocess.run(command, shell=True, check=True, text=True, capture_output=True)
            sts_info = json.loads(result.stdout)

            ready_replicas = sts_info.get('status', {}).get('readyReplicas', 0)
            desired_replicas = sts_info.get('spec', {}).get('replicas', 0)

            if desired_replicas > 0 and ready_replicas == desired_replicas:
                print(f"VoltDB StatefulSet '{statefulset_name}' is ready ({ready_replicas}/{desired_replicas} replicas).")
                return True
            else:
                print(f"  VoltDB StatefulSet '{statefulset_name}' not yet ready ({ready_replicas}/{desired_replicas} replicas). Retrying in 10 seconds...")

        except subprocess.CalledProcessError as e:
            # StatefulSet might not exist yet or other kubectl error.
            # In this polling loop, if it's NotFound, it's fine to just retry.
            print(f"  Error checking statefulset status: {e.stderr.strip()}. Retrying in 10 seconds...")
        except json.JSONDecodeError:
            print(f"  Failed to parse kubectl JSON output for StatefulSet. Retrying in 10 seconds...")
        except Exception as e:
            print(f"  An unexpected error occurred during StatefulSet check: {e}. Retrying in 10 seconds...")

        time.sleep(10)

    print(f"Timeout: VoltDB StatefulSet '{statefulset_name}' did not become ready within {timeout_seconds} seconds.")
    return False

# --- Main Installation Logic (for VoltDB Core) ---

def main():
    """
    Main function for the VoltDB Core setup script.
    """
    print("\n--- Starting VoltDB Core installation ---")

    # Arguments received from vwap_setup.py
    if len(sys.argv) < 3:
        print("Error: Missing arguments for Redpanda details.")
        print("Expected: red_panda_release redpanda_namespace")
        sys.exit(1)

    red_panda_release = sys.argv[1]
    redpanda_namespace = sys.argv[2]

    print(f"Received Redpanda details: Release='{red_panda_release}', Namespace='{redpanda_namespace}'")

    # Add VoltDB Helm repo (always try to add/update to ensure it's present and current)
    print("Adding VoltDB Helm repository...")
    add_repo_command = "helm repo add voltdb https://voltdb.github.io/helm-charts"
    try:
        # Suppress stdout if repo already exists, to reduce verbosity
        subprocess.run(add_repo_command, shell=True, check=True, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        print("VoltDB repository added successfully.")
    except subprocess.CalledProcessError as e:
        if "Error: repository name (voltdb) already exists" in e.stderr:
            print("VoltDB repository already exists. Continuing...")
        else:
            print(f"Error adding VoltDB repository: {e.stderr}")
            sys.exit(1)

    # Update Helm repos, suppressing verbose output if successful
    print("Updating Helm repositories...")
    try:
        subprocess.run("helm repo update", shell=True, check=True, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        print("Helm repositories updated.") # More concise confirmation
    except subprocess.CalledProcessError as e:
        print(f"Error updating Helm repositories: {e.stderr}")
        sys.exit(1)


    # Get user inputs for VoltDB Core cluster and namespace
    volt_ns = get_user_input("Enter Namespace to install VoltDB Core", default="voltdb")
    # Create namespace if it's doesn't exist
    create_namespace_if_not_exists(volt_ns)

    volt_cluster_name = get_user_input("Enter the VoltDB Cluster Name", default="volt-vwap")
    
    # Flag to determine if installation should proceed or if we just wait
    install_new_cluster = False
    # Corrected secret name to match what Helm chart ServiceAccounts expect
    docker_secret_name = "dockerio-registry"
    
    # --- Helm Release Existence Check ---
    print(f"\nChecking if Helm release '{volt_cluster_name}' already exists in namespace '{volt_ns}'...")
    helm_status_cmd = f"helm status {volt_cluster_name} -n {volt_ns}"
    helm_release_exists = False
    try:
        subprocess.run(helm_status_cmd, shell=True, check=True, text=True, 
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) # Suppress helm status output
        helm_release_exists = True
    except subprocess.CalledProcessError:
        helm_release_exists = False

    if helm_release_exists:
        print(f"Helm release '{volt_cluster_name}' already exists in namespace '{volt_ns}'.")
        # Check if the StatefulSet *associated with this release* exists and is healthy
        if check_statefulset_exists_and_ready(volt_cluster_name, volt_ns): # This function now uses the correct STS name
            print(f"VoltDB Cluster '{volt_cluster_name}' is already healthy and ready. Proceeding to next step.")
            install_new_cluster = False # Don't install, just wait
        else:
            # Helm release exists, but StatefulSet is missing or unhealthy
            print(f"WARNING: Helm release '{volt_cluster_name}' exists, but its StatefulSet is missing or unhealthy.")
            action = get_user_input(
                "Do you want to (1) try to uninstall the existing Helm release, or (2) abort and fix manually? (1/2): ",
                default="1"
            )
            if action == "1":
                print(f"Attempting to uninstall Helm release '{volt_cluster_name}'...")
                uninstall_cmd = f"helm uninstall {volt_cluster_name} -n {volt_ns}"
                run_command(uninstall_cmd, "Uninstalling VoltDB Helm release...", exit_on_error=False)
                # After uninstall, we treat it as a new installation opportunity
                install_new_cluster = True
                print(f"Helm release '{volt_cluster_name}' uninstalled (or attempted). Proceeding with new installation.")
            else:
                print(f"Aborting. Please manually uninstall the existing Helm release '{volt_cluster_name}' (e.g., 'helm uninstall {volt_cluster_name} -n {volt_ns}') and re-run the script.")
                sys.exit(0)
    else:
        print(f"Helm release '{volt_cluster_name}' does not exist in namespace '{volt_ns}'. Proceeding with new installation.")
        install_new_cluster = True

    if install_new_cluster:
        # --- Docker Registry Secret for VoltDB Core ---
        print("\n--- Docker Registry Credentials (for VoltDB Core images) ---")
        create_secret = get_user_input("Do you need to create/update a Docker registry secret for VoltDB Core? (yes/no)", default="yes")

        if create_secret.lower() == "yes":
            # Using the corrected docker_secret_name
            if check_kubernetes_secret_exists(docker_secret_name, volt_ns):
                print(f"Kubernetes Secret '{docker_secret_name}' already exists in namespace '{volt_ns}'. Skipping creation.")
            else:
                print(f"Creating Kubernetes Secret '{docker_secret_name}' in namespace '{volt_ns}'.")
                # Removed the prompt for docker_server as it's hardcoded to "docker.io"
                docker_server = "docker.io" # Hardcoded
                docker_username = get_user_input("Enter Docker Username")
                docker_password = get_user_input("Enter Docker Password", sensitive=True)
                docker_email = get_user_input("Enter Docker Email (optional)", default="")

                create_secret_cmd = (
                    f"kubectl create secret docker-registry {docker_secret_name} "
                    f"--docker-server={docker_server} "
                    f"--docker-username={docker_username} "
                    f"--docker-password={docker_password} "
                    f"{f'--docker-email={docker_email}' if docker_email else ''} "
                    f"-n {volt_ns}"
                )
                run_command(create_secret_cmd, "Creating Docker registry secret...")
                print(f"Docker registry secret '{docker_secret_name}' created successfully in namespace '{volt_ns}'.")
        else:
            print("Skipping Docker registry secret creation for VoltDB Core.")

        # Prompt for VoltDB Version (CRITICAL FIX for Helm error)
        print("\nNote: The VoltDB Helm chart requires a specific VoltDB version (e.g., 13.3.6, 14.1.0).")
        voltdb_version = get_user_input("Enter the VoltDB product version", default="13.3.6")

        # Prompt for license file, DDL, and JAR
        default_license_path = "/Users/gulshansharma/Desktop/VoltActiveDataGulshan_Enterprise_XDCR_Expires-2026-02-15.xml"
        license_xml_path = get_user_input(f"Enter path to VoltDB license XML file", default=default_license_path)

        default_ddl_path = "/Users/gulshansharma/Downloads/voltsptest1/vwap_ddl.sql"
        ddl_path = get_user_input(f"Enter path to VoltDB DDL file", default=default_ddl_path)

        default_jar_path = "/Users/gulshansharma/Downloads/voltsptest1/vwap_demo.jar"
        jar_path = get_user_input(f"Enter path to VoltDB application JAR file (e.g., vwap_demo.jar)", default=default_jar_path)

        # Check if local files exist before proceeding
        if not os.path.exists(license_xml_path):
            print(f"Error: VoltDB license file not found at {license_xml_path}")
            sys.exit(1)
        if not os.path.exists(ddl_path):
            print(f"Error: VoltDB DDL file not found at {ddl_path}")
            sys.exit(1)
        if not os.path.exists(jar_path):
            print(f"Error: VoltDB application JAR file not found at {jar_path}")
            sys.exit(1)

        # Install VoltDB Core command, adjusted to match your successful command format
        install_voltdb_cmd = (
            f"helm install {volt_cluster_name} voltdb/voltdb "
            f"--set global.voltdbVersion={voltdb_version} "
            f"--set-file cluster.config.licenseXMLFile={license_xml_path} "
            f"--set cluster.clusterSpec.replicas=1 "
            f"--set cluster.config.deployment.cluster.kfactor=0 "
            f"--set cluster.config.deployment.cluster.sitesperhost=8 "
            f"--set-file cluster.config.schemas.vwap_ddl_sql={ddl_path} "
            f"--set-file cluster.config.classes.vwap_demo_jar={jar_path} "
            f"--set security.internalHostAuth.enabled=true "
            f"--set imagePullSecrets[0].name={docker_secret_name} "
            f"-n {volt_ns}"
        )
        run_command(install_voltdb_cmd, "Installing VoltDB Core...")

        # ADDED SLEEP HERE AFTER HELM INSTALL
        print("Sleeping for 10 seconds to allow Kubernetes API and operator to reconcile...")
        time.sleep(10)

    # --- WAITING LOGIC FOR VOLTDB CORE DEPLOYMENT ---
    # This block runs whether the cluster was just installed or already existed
    statefulset_to_wait_for = get_voltdb_statefulset_name(volt_cluster_name)
    print(f"Waiting for VoltDB StatefulSet '{statefulset_to_wait_for}' rollout to complete in namespace '{volt_ns}'...")
    
    # Wait for the StatefulSet object to exist first (essential for operator-managed resources)
    if not wait_for_statefulset_object_to_exist(statefulset_to_wait_for, volt_ns):
        print(f"VoltDB StatefulSet '{statefulset_to_wait_for}' did not appear in time. Cannot proceed with rollout status.")
        sys.exit(1)

    # Add a small sleep here to allow Kubernetes API to settle before rollout status check
    time.sleep(5) 

    # Initial check and short retry for rollout status
    max_retries = 5
    retry_delay = 5 # seconds
    rollout_successful = False
    for i in range(max_retries):
        try:
            print(f"Attempt {i+1}/{max_retries}: Checking rollout status for {statefulset_to_wait_for}...")
            # Display output directly, no capture_output for rollout status
            subprocess.run(f"kubectl rollout status statefulset/{statefulset_to_wait_for} -n {volt_ns} --timeout=900s",
                           shell=True, check=True, text=True, capture_output=False) # Display output directly
            rollout_successful = True
            break
        except subprocess.CalledProcessError as e:
            # Check if stderr is available and contains "NotFound"
            error_output_str = e.stderr if e.stderr is not None else ""
            if "NotFound" in error_output_str and i < max_retries - 1:
                print(f"StatefulSet '{statefulset_to_wait_for}' not found by rollout status yet. Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print(f"Error executing kubectl rollout status: {error_output_str}")
                sys.exit(1)
    
    if not rollout_successful:
        print("Failed to get successful rollout status after multiple retries.")
        sys.exit(1)

    # The more robust wait using `kubectl get statefulset -o json` is handled by wait_for_voltdb_cluster_ready
    if not wait_for_voltdb_cluster_ready(volt_cluster_name, volt_ns): # This function now internally uses the derived name
        print("VoltDB cluster did not become ready within the timeout. Please check cluster status manually.")
        sys.exit(1)
    
    print("VoltDB Core cluster is ready.")
    print("VoltDB Core installation complete.")

    # --- Insert dummy record into VoltDB ---
    print("\n--- Inserting a dummy record into VoltDB 'DUMMY' table ---")
    insert_dummy_cmd = (
        f"kubectl exec -it {get_voltdb_statefulset_name(volt_cluster_name)}-0 -n {volt_ns} " # Use -0 for the first pod in STS
        f"-- sqlcmd --query=\"insert into DUMMY values 'X';\""
    )
    # Give a short moment for the sqlcmd to be ready if pod just transitioned to Running
    time.sleep(5)
    run_command(insert_dummy_cmd, "Attempting to insert dummy record...")
    print("Dummy record insertion command executed. Please verify in VoltDB.")


    # --- Call the VoltSP setup script after VoltDB Core is ready ---
    print("\n--- Starting VoltSP pipeline setup script... ---")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    voltsp_script_path = os.path.join(script_dir, "voltsp_setup.py")

    try:
        # Pass Redpanda and VoltDB core details to voltsp_setup.py
        subprocess.run([sys.executable, voltsp_script_path, red_panda_release, redpanda_namespace, volt_cluster_name, volt_ns], check=True)
        print("\nVoltSP setup completed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"\nVoltSP setup failed: {e}")
        print(f"Stderr from voltsp_setup.py: {e.stderr}")
        print(f"Stdout from voltsp_setup.py: {e.stdout}")
        sys.exit(1)


if __name__ == "__main__":
    main()
