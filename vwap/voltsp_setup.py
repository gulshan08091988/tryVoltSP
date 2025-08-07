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
    except subprocess.CalledCalledProcessError as e: # Corrected from CalledProcessError
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

    red_panda_release = sys.argv[1] # e.g., redpanda-cluster
    redpanda_namespace = sys.argv[2] # e.g., test
    volt_cluster_name = sys.argv[3] # e.g., volt-vwap
    volt_ns = sys.argv[4] # e.g., voltdb

    print(f"Received Redpanda details: Release='{red_panda_release}', Namespace='{redpanda_namespace}'")
    print(f"Received VoltDB details: Cluster='{volt_cluster_name}', Namespace='{volt_ns}'")

    pipeline_name = get_user_input("Enter the VoltSP Pipeline Name", default="pipeline1")
    voltsp_ns = get_user_input("Enter Namespace to install VoltSP", default=volt_ns)
    
    # Check for and create the namespace if it doesn't exist
    create_namespace_if_not_exists(voltsp_ns)
    
    # Removed yq prerequisite check as it's no longer needed in this script.

    # --- Docker Registry Secret ---
    print("\n--- Docker Registry Credentials (for VoltSP images) ---")
    create_secret = get_user_input("Do you need to create/update a Docker registry secret for VoltSP? (yes/no)", default="yes")

    docker_secret_name = "voltsp-docker-registry-secret" # Default secret name for VoltSP
    
    if create_secret.lower() == "yes":
        if check_kubernetes_secret_exists(docker_secret_name, voltsp_ns):
            print(f"Kubernetes Secret '{docker_secret_name}' already exists in namespace '{voltsp_ns}'. Skipping creation.")
        else:
            print(f"Creating Kubernetes Secret '{docker_secret_name}' in namespace '{voltsp_ns}'.")
            docker_server = "docker.io" # Hardcoded to docker.io as per request
            docker_username = get_user_input("Enter Docker Username")
            docker_password = get_user_input("Enter Docker Password", sensitive=True)
            docker_email = get_user_input("Enter Docker Email", default="")

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
    cwd = os.path.dirname(os.path.abspath(__file__))
    default_license_path = os.path.join(cwd, "license", "license.xml")
    license_xml_path = get_user_input(f"Enter path to VoltSP license XML file", default=default_license_path)

    cwd = os.path.dirname(os.path.abspath(__file__))
    default_jar_path = os.path.join(cwd, "jars", "vwap-demo-1.0-SNAPSHOT-voltsp-kafka-reader-stream.jar")
    voltsp_jar_path = get_user_input(f"Enter path to VoltSP Kafka Reader Stream JAR file", default=default_jar_path)

    # Check if local files exist before proceeding
    if not os.path.exists(license_xml_path):
        print(f"Error: VoltSP license file not found at {license_xml_path}")
        sys.exit(1)
    if not os.path.exists(voltsp_jar_path):
        print(f"Error: VoltSP JAR file not found at {voltsp_jar_path}")
        sys.exit(1)

    # --- Generate voltsp.yaml content dynamically ---
    temp_voltsp_values_file = None
    try:
        print(f"\nDynamically generating VoltSP configuration...")
        
        # Determine dynamic addresses
        # Redpanda broker address: <release-name>.<namespace>.svc.cluster.local:<kafka-port>
        redpanda_broker_addr = f"{red_panda_release}.{redpanda_namespace}.svc.cluster.local:9093"
        # VoltDB client address: <cluster-name>-voltdb-cluster-client.<namespace>.svc.cluster.local:<client-port>
        voltdb_client_addr = f"{volt_cluster_name}-voltdb-cluster-client.{volt_ns}.svc.cluster.local:21212"

        print(f"  Generated Kafka bootstrapServers: {redpanda_broker_addr}")
        print(f"  Generated VoltDB sink servers: {voltdb_client_addr}")

        # Define the voltsp.yaml content as a multi-line string with placeholders
        voltsp_values_template = f"""
resources:
  limits:
    cpu: 2
    memory: 2G
  requests:
    cpu: 2
    memory: 2G

streaming:
  pipeline:
    className: com.voltactivedata.vwapdemo.voltsp.ReadFromKafkaAndSendToVoltTickers

    configuration:
      sink:
        voltdb-procedure:
          servers: {voltdb_client_addr}
          procedureName: ReportTickSessionAnchor
      source:
        kafka:
          topicNames: "ticker-data"
          bootstrapServers: {redpanda_broker_addr}
          groupId: "1"
"""
        # Write the dynamically generated content to a temporary file
        temp_voltsp_values_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml')
        temp_voltsp_values_path = temp_voltsp_values_file.name
        temp_voltsp_values_file.write(voltsp_values_template.strip()) # .strip() removes leading/trailing whitespace
        temp_voltsp_values_file.close() # Close to ensure content is flushed

        print(f"  Generated VoltSP configuration written to temporary file: {temp_voltsp_values_path}")

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
                f"--values {temp_voltsp_values_path} " # Use the temporary, dynamically generated values file
                f"--set imagePullSecrets[0].name={docker_secret_name} "
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
        # Clean up the temporary values file
        if temp_voltsp_values_file and os.path.exists(temp_voltsp_values_path):
            os.remove(temp_voltsp_values_path)

# --- Call the VWAP App setup script ---
    print("\n--- Starting VWAP Load Generator setup script... ---")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    vwap_loadgen_script_path = os.path.join(script_dir, "vwap_loadgen_setup.py")

    try:
        # Pass the current VoltSP namespace (which is loadgen_ns),
        # Redpanda namespace, and VoltDB namespace
        subprocess.run([sys.executable, 
                        vwap_loadgen_script_path, 
                        voltsp_ns, # This is the namespace for the loadgen (usually same as voltsp)
                        redpanda_namespace, # Redpanda's namespace
                        volt_ns], # VoltDB's namespace
                       check=True)
        print("\nVWAP Load Generator setup completed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"\nVWAP Load Generator setup failed: {e}")
        print(f"Stderr from vwap_loadgen_setup.py: {e.stderr}")
        print(f"Stdout from vwap_loadgen_setup.py: {e.stdout}")
        sys.exit(1)


if __name__ == "__main__":
    main()
