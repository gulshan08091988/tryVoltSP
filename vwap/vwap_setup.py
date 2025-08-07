import subprocess
import sys
import time
import os
import json

# --- Helper Functions (Shared - could be moved to a common utility file) ---
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
            # CORRECTED: Removed capture_output=True when stdout/stderr are explicitly set
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
        import getpass
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

# --- Custom Waiting Functions (for Redpanda) ---

def wait_for_redpanda_pods_ready(release_name, namespace, timeout_seconds=600):
    """
    Waits until all Redpanda broker pods (2/2 Ready) are ready by polling.
    """
    start_time = time.time()
    print(f"Starting custom wait for Redpanda broker pods in namespace '{namespace}' (timeout: {timeout_seconds}s)...")

    total_expected_pods = 3 # Redpanda statefulset.replicas=3

    while time.time() - start_time < timeout_seconds:
        command = (
            f"kubectl get pods -n {namespace} "
            f"-l app.kubernetes.io/instance={release_name},app.kubernetes.io/name=redpanda "
            f"--field-selector=status.phase=Running "
            f"-o json"
        )
        try:
            result = subprocess.run(command, shell=True, check=True, text=True, capture_output=True)
            pods_info = json.loads(result.stdout)

            ready_pods_count = 0

            for pod in pods_info.get('items', []):
                pod_is_ready = False
                for condition in pod.get('status', {}).get('conditions', []):
                    if condition['type'] == 'Ready' and condition['status'] == 'True':
                        pod_is_ready = True
                        break

                if pod_is_ready:
                    ready_pods_count += 1

            if ready_pods_count == total_expected_pods:
                print(f"All {total_expected_pods} Redpanda broker pods are ready.")
                return True
            else:
                print(f"  {ready_pods_count}/{total_expected_pods} Redpanda broker pods ready. Retrying in 10 seconds...")

        except subprocess.CalledProcessError as e:
            print(f"  Error checking pod status: {e.stderr.strip()}. Retrying in 10 seconds...")
        except json.JSONDecodeError:
            print(f"  Failed to parse kubectl JSON output. Retrying in 10 seconds...")
        except Exception as e:
            print(f"  An unexpected error occurred during pod check: {e}. Retrying in 10 seconds...")

        time.sleep(10)

    print(f"Timeout: Redpanda broker pods did not become ready within {timeout_seconds} seconds.")
    return False

# --- Main Installation Logic (for Redpanda only) ---

def main():
    """
    Main function for the VWAP setup script (Redpanda part).
    This script is called by tryVoltSP.py.
    """
    print("\n--- Starting Redpanda installation for VWAP demo ---")

    # --- Helm Repo Add/Update (moved to top, made less verbose) ---
    print("Adding Redpanda Helm repository...")
    add_repo_command = "helm repo add redpanda https://charts.redpanda.com/"
    try:
        # CORRECTED: Removed capture_output=True for helm repo add when stdout is DEVNULL
        subprocess.run(add_repo_command, shell=True, check=True, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        print("Redpanda repository added successfully.")
    except subprocess.CalledProcessError as e:
        if "Error: repository name (redpanda) already exists" in e.stderr:
            print("Redpanda repository already exists. Continuing...")
        else:
            print(f"Error adding Redpanda repository: {e.stderr}")
            sys.exit(1)

    # Update Helm repos, suppressing verbose output if successful
    # The `run_command` helper itself needs to be fixed if it uses `capture_output=True` alongside `suppress_stdout=True`
    # Let's directly call subprocess for this specific verbose command, or fix run_command's internal logic.
    # For now, making it use `subprocess.DEVNULL` for its normal output.
    print("Updating Helm repositories...")
    try:
        subprocess.run("helm repo update", shell=True, check=True, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        print("Helm repositories updated.") # More concise confirmation
    except subprocess.CalledProcessError as e:
        print(f"Error updating Helm repositories: {e.stderr}")
        sys.exit(1)


    # --- Namespace and Release Name Input (Order adjusted) ---
    redpanda_namespace = get_user_input("Enter Namespace for Redpanda", default="default")
    create_namespace_if_not_exists(redpanda_namespace) # Ensure namespace exists first

    red_panda_release = get_user_input("Enter the Redpanda Helm release name", default="redpanda-cluster")

    # --- Redpanda Helm Release Existence Check ---
    install_new_redpanda = False
    print(f"\nChecking if Helm release '{red_panda_release}' already exists in namespace '{redpanda_namespace}'...")
    helm_status_cmd = f"helm status {red_panda_release} -n {redpanda_namespace}"
    helm_release_exists = False
    try:
        subprocess.run(helm_status_cmd, shell=True, check=True, text=True, 
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) # Suppress helm status output
        helm_release_exists = True
    except subprocess.CalledProcessError:
        helm_release_exists = False

    if helm_release_exists:
        print(f"Helm release '{red_panda_release}' already exists in namespace '{redpanda_namespace}'.")
        print("Proceeding to wait for existing Redpanda cluster readiness.")
        install_new_redpanda = False
    else:
        print(f"Helm release '{red_panda_release}' does not exist in namespace '{redpanda_namespace}'. Installing it now.")
        install_new_redpanda = True

    if install_new_redpanda:
        # Install Redpanda command
        install_redpanda_cmd = (
            f"helm upgrade --install \"{red_panda_release}\" redpanda/redpanda "
            f"--set statefulset.replicas=3 "
            f"--set tls.enabled=false "
            f"--version 25.1.1 "
            f"-n {redpanda_namespace}"
        )
        run_command(install_redpanda_cmd, "Installing Redpanda...")

    # --- WAITING LOGIC ---
    print(f"Waiting for Redpanda StatefulSet '{red_panda_release}' rollout to complete in namespace '{redpanda_namespace}'...")
    
    # Use a retry loop for kubectl rollout status for robustness
    max_retries = 5
    retry_delay = 5 # seconds
    rollout_successful = False
    for i in range(max_retries):
        try:
            print(f"Attempt {i+1}/{max_retries}: Checking rollout status for {red_panda_release}...")
            subprocess.run(f"kubectl rollout status statefulset/{red_panda_release} -n {redpanda_namespace} --timeout=600s",
                           shell=True, check=True, text=True, capture_output=False) # Display output directly
            rollout_successful = True
            break
        except subprocess.CalledProcessError as e:
            if "NotFound" in e.stderr and i < max_retries - 1:
                print(f"StatefulSet '{red_panda_release}' not found yet. Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print(f"Error executing kubectl rollout status: {e.stderr}")
                sys.exit(1)
    
    if not rollout_successful:
        print("Failed to get successful rollout status after multiple retries.")
        sys.exit(1)

    if not wait_for_redpanda_pods_ready(red_panda_release, redpanda_namespace):
        print("Redpanda cluster did not become ready within the timeout. Please check cluster status manually.")
        sys.exit(1)

    print("Redpanda cluster is ready.")

    # Step 5: Redpanda Topic Configuration
    print("\nRedpanda cluster is ready. Creating and configuring topic 'ticker-data'...")

    topic_name = "ticker-data"
    # Execute rpk command via one of the redpanda pods. We need the pod name.
    # Get a running pod name dynamically.
    get_redpanda_pod_cmd = (
        f"kubectl get pods -n {redpanda_namespace} "
        f"-l app.kubernetes.io/instance={red_panda_release},app.kubernetes.io/name=redpanda "
        f"-o jsonpath='{{.items[0].metadata.name}}'"
    )
    redpanda_pod_name = run_command(get_redpanda_pod_cmd, "Getting Redpanda pod name...", exit_on_error=True).strip()
    
    if not redpanda_pod_name:
        print("Error: Could not determine Redpanda pod name to configure topic.")
        sys.exit(1)

    check_topic_cmd = f"kubectl exec {redpanda_pod_name} -n {redpanda_namespace} -c redpanda -- rpk topic list | grep -w {topic_name}"

    topic_exists_process = subprocess.run(check_topic_cmd, shell=True, text=True, capture_output=True, check=False)

    if topic_exists_process.returncode == 0:
        print(f"Topic '{topic_name}' already exists. Skipping topic creation.")
    else:
        create_topic_cmd = (
            f"kubectl exec {redpanda_pod_name} -n {redpanda_namespace} -c redpanda -- "
            f"rpk topic create {topic_name} --partitions 15 --replicas 1 "
            f"--brokers {red_panda_release}-0.{red_panda_release}.{redpanda_namespace}.svc.cluster.local:9093" # Assumes internal broker address
        )
        run_command(create_topic_cmd, f"Creating '{topic_name}' topic...")

    alter_topic_cmd = (
        f"kubectl exec {redpanda_pod_name} -n {redpanda_namespace} -c redpanda -- "
        f"rpk topic alter-config {topic_name} --set compression.type=lz4 "
        f"--set segment.bytes=268435456 --set retention.ms=12000000 --set cleanup.policy=delete "
        f"--brokers {red_panda_release}-0.{red_panda_release}.{redpanda_namespace}.svc.cluster.local:9093" # Assumes internal broker address
    )
    run_command(alter_topic_cmd, f"Altering '{topic_name}' topic configuration...")

    print("\nRedpanda topic 'ticker-data' configured successfully.")
    print("Redpanda setup is complete!")

    # --- Call the VoltDB core setup script after Redpanda is ready ---
    print("\n--- Starting VoltDB core setup script... ---")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # CORRECTED: Calling voltdb_core_setup.py
    voltdb_script_path = os.path.join(script_dir, "voltdb_core_setup.py")

    try:
        # Pass Redpanda release name and namespace as arguments to voltdb_core_setup.py
        subprocess.run([sys.executable, voltdb_script_path, red_panda_release, redpanda_namespace], check=True)
        print("\nVoltDB core and VoltSP setup completed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"\nVoltDB core or VoltSP setup failed: {e}")
        print(f"Stderr from voltdb_core_setup.py: {e.stderr}")
        print(f"Stdout from voltdb_core_setup.py: {e.stdout}")
        sys.exit(1)

if __name__ == "__main__":
    main()
