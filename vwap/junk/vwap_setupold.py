import subprocess
import sys
import time
import os
import json

# --- Helper Functions (Shared) ---
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

    red_panda_release = get_user_input("Enter the Redpanda Helm release name", default="redpanda-cluster")
    redpanda_namespace = get_user_input("Enter Namespace for Redpanda", default="default")

    # Add Redpanda Helm repo
    print("Adding Redpanda Helm repository...")
    add_repo_command = "helm repo add redpanda https://charts.redpanda.com/"
    try:
        subprocess.run(add_repo_command, shell=True, check=True, text=True, capture_output=True)
        print("Redpanda repository added successfully.")
    except subprocess.CalledProcessError as e:
        if "Error: repository name (redpanda) already exists" in e.stderr:
            print("Redpanda repository already exists. Continuing...")
        else:
            print(f"Error adding Redpanda repository: {e.stderr}")
            sys.exit(1)

    # Update Helm repos
    run_command("helm repo update", "Updating Helm repositories...")

    # Create namespace if it doesn't exist
    run_command(f"kubectl create namespace {redpanda_namespace} --dry-run=client -o yaml | kubectl apply -f -", f"Ensuring namespace '{redpanda_namespace}' exists...")

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
    run_command(f"kubectl rollout status statefulset/{red_panda_release} -n {redpanda_namespace} --timeout=600s",
                "Waiting for Redpanda StatefulSet rollout...", exit_on_error=True)

    if not wait_for_redpanda_pods_ready(red_panda_release, redpanda_namespace):
        print("Redpanda cluster did not become ready within the timeout. Please check cluster status manually.")
        sys.exit(1)

    print("Redpanda cluster is ready.")

    # Step 5: Redpanda Topic Configuration
    print("\nRedpanda cluster is ready. Creating and configuring topic 'ticker-data'...")

    topic_name = "ticker-data"
    check_topic_cmd = f"kubectl exec {red_panda_release}-0 -n {redpanda_namespace} -c redpanda -- rpk topic list | grep -w {topic_name}"

    topic_exists_process = subprocess.run(check_topic_cmd, shell=True, text=True, capture_output=True, check=False)

    if topic_exists_process.returncode == 0:
        print(f"Topic '{topic_name}' already exists. Skipping topic creation.")
    else:
        create_topic_cmd = (
            f"kubectl exec {red_panda_release}-0 -n {redpanda_namespace} -c redpanda -- "
            f"rpk topic create {topic_name} --partitions 15 --replicas 1 "
            f"--brokers {red_panda_release}-0.{red_panda_release}.{redpanda_namespace}.svc.cluster.local:9093"
        )
        run_command(create_topic_cmd, f"Creating '{topic_name}' topic...")

    alter_topic_cmd = (
        f"kubectl exec {red_panda_release}-0 -n {redpanda_namespace} -c redpanda -- "
        f"rpk topic alter-config {topic_name} --set compression.type=lz4 "
        f"--set segment.bytes=268435456 --set retention.ms=12000000 --set cleanup.policy=delete "
        f"--brokers {red_panda_release}-0.{red_panda_release}.{redpanda_namespace}.svc.cluster.local:9093"
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
