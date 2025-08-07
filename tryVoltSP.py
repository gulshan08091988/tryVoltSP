import subprocess
import sys
import os
import time
import json # Will need this for parsing gcloud describe output

# --- Helper Functions ---

def run_command(command, message="", exit_on_error=True):
    """
    Runs a shell command, prints messages, and optionally exits on error.
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

def get_user_input(prompt, default=""):
    """
    Gets user input with an optional default value.
    """
    if default:
        return input(f"{prompt} (default: {default}): ") or default
    else:
        return input(f"{prompt}: ")

def check_gke_cluster_exists(project_id, cluster_name, zone):
    """
    Checks if a GKE cluster already exists in a specific project and zone.
    Returns True if it exists, False otherwise.
    """
    print(f"Checking if GKE cluster '{cluster_name}' exists in project '{project_id}' and zone '{zone}'...")
    command = f"gcloud container clusters list --project {project_id} --filter='name={cluster_name} AND zone={zone}' --format='value(name)'"
    try:
        output = subprocess.run(command, shell=True, check=False, text=True, capture_output=True).stdout.strip()
        return output == cluster_name
    except Exception as e:
        print(f"An error occurred while checking cluster existence: {e}")
        return False

def wait_for_gke_cluster_ready(project_id, cluster_name, zone, timeout_seconds=900): # 15 minutes timeout
    """
    Waits for a GKE cluster to reach the 'RUNNING' status.
    Returns True if the cluster becomes ready within the timeout, False otherwise.
    """
    print(f"Waiting for GKE cluster '{cluster_name}' to become RUNNING (timeout: {timeout_seconds}s)...")
    start_time = time.time()
    
    while time.time() - start_time < timeout_seconds:
        command = f"gcloud container clusters describe {cluster_name} --zone {zone} --project {project_id} --format=json"
        try:
            result = subprocess.run(command, shell=True, check=True, text=True, capture_output=True)
            cluster_info = json.loads(result.stdout)
            status = cluster_info.get('status')
            
            if status == "RUNNING":
                print(f"GKE cluster '{cluster_name}' is now RUNNING.")
                return True
            elif status in ["PROVISIONING", "RECONCILING", "STOPPING"]:
                print(f"  Cluster status: {status}. Waiting for RUNNING... Retrying in 30 seconds.")
            else:
                print(f"  Cluster status: {status}. Unexpected status, might be an error. Retrying in 30 seconds.")
                # You might want to add more sophisticated error handling here, e.g., if status is "ERROR"
            
        except subprocess.CalledProcessError as e:
            # If describe fails, e.g., cluster doesn't exist yet (unlikely in this flow) or other API error
            print(f"  Error describing cluster: {e.stderr.strip()}. Retrying in 30 seconds.")
        except json.JSONDecodeError:
            print(f"  Failed to parse gcloud JSON output. Retrying in 30 seconds.")
        except Exception as e:
            print(f"  An unexpected error occurred during cluster status check: {e}. Retrying in 30 seconds.")
            
        time.sleep(30) # Wait before retrying

    print(f"Timeout: GKE cluster '{cluster_name}' did not become RUNNING within {timeout_seconds} seconds.")
    return False


# --- Main Function ---

def main():
    print("Welcome to tryVoltSP.")

    action = get_user_input("Enter gke to eks: ", default="gke")

    if action.lower() != "gke":
        print("Invalid input. This script currently only supports 'gke' for cluster operations.")
        sys.exit(1)

    # 1. Get GCP Project ID and set it immediately
    gcp_project_id = get_user_input("Enter your GCP Project ID")
    if not gcp_project_id:
        print("GCP Project ID cannot be empty. Exiting.")
        sys.exit(1)
    run_command(f"gcloud config set project {gcp_project_id}", f"Setting gcloud project to {gcp_project_id}...")

    # 2. Get GKE Cluster Name
    gke_cluster_name = get_user_input("Enter the GKE cluster name", default="voltsp")
    default_gcp_zone = "asia-northeast1-b" # Define a default zone for initial check

    # 3. Check for existing cluster
    cluster_exists_in_default_zone = check_gke_cluster_exists(gcp_project_id, gke_cluster_name, default_gcp_zone)

    gcp_zone = default_gcp_zone # Initialize with default zone, will be overridden if new cluster

    if cluster_exists_in_default_zone:
        print(f"Cluster '{gke_cluster_name}' already exists in zone '{default_gcp_zone}'.")
        proceed_with_existing = get_user_input(
            f"Do you want to proceed with the existing cluster '{gke_cluster_name}' in zone '{default_gcp_zone}'? (yes/no): ",
            default="yes"
        )
        if proceed_with_existing.lower() != "yes":
            print("Aborting cluster operation as you chose not to proceed with the existing cluster.")
            sys.exit(0)
        else:
            print(f"Proceeding with existing GKE cluster: {gke_cluster_name} in zone {gcp_zone}")
            # IMPORTANT: Wait for the existing cluster to be ready
            if not wait_for_gke_cluster_ready(gcp_project_id, gke_cluster_name, gcp_zone):
                print("Existing GKE cluster is not ready. Aborting.")
                sys.exit(1)
    else:
        # Cluster does not exist, so ask for all creation parameters
        print(f"Cluster '{gke_cluster_name}' does not exist in zone '{default_gcp_zone}'.")
        print("Please provide details to create a new GKE cluster.")
        gcp_zone = get_user_input("Enter the GCP zone", default=default_gcp_zone) # User can specify a different zone for new cluster
        gke_cluster_version = get_user_input("Enter the GKE cluster version", default="1.32")
        num_nodes = get_user_input("Enter the number of nodes", default="6")
        machine_type = get_user_input("Enter the machine type", default="c2-standard-16")
        disk_size_gb = get_user_input("Enter the disk size (GB)", default="50")
        disk_type = get_user_input("Enter the disk type", default="pd-ssd")

        print(f"Creating GKE cluster '{gke_cluster_name}'...")
        create_cluster_cmd = (
            f"gcloud container clusters create {gke_cluster_name} "
            f"--project {gcp_project_id} "
            f"--zone {gcp_zone} "
            f"--cluster-version {gke_cluster_version} "
            f"--num-nodes {num_nodes} "
            f"--machine-type {machine_type} "
            f"--disk-size {disk_size_gb} "
            f"--disk-type {disk_type} "
            "--enable-ip-alias "
            f"--node-locations {gcp_zone}" # Node locations typically match the zone for single-zone clusters
        )
        run_command(create_cluster_cmd, "Creating the GKE cluster. This may take a few minutes...")
        
        # IMPORTANT: Wait for the newly created cluster to be ready
        if not wait_for_gke_cluster_ready(gcp_project_id, gke_cluster_name, gcp_zone):
            print("Newly created GKE cluster did not become ready. Aborting.")
            sys.exit(1)


    # Regardless of whether it's new or existing, get credentials for the cluster now that it's confirmed RUNNING
    run_command(f"gcloud container clusters get-credentials {gke_cluster_name} --zone {gcp_zone} --project {gcp_project_id}",
                "Configuring kubectl to connect to the GKE cluster...")

    print("\nGKE cluster is ready.")

    # --- Demo Application Selection ---
    print("\nPlease select a demo application to proceed:")
    print("1) VWAP (Volume Weighted Average Price)")
    print("2) testdemo")

    app_choice = get_user_input("Enter your choice (1 or 2): ")

    if app_choice == "1":
        print("\n--- You selected VWAP. Starting VWAP setup script (Redpandam VoltDB , VoltSP & VWAP Load Generator )... ---")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        vwap_script_path = os.path.join(script_dir, "vwap", "vwap_setup.py")

        try:
            subprocess.run([sys.executable, vwap_script_path], check=True)
            print("\nVWAP demo application setup completed successfully!")
        except subprocess.CalledProcessError as e:
            print(f"\nVWAP demo application setup failed: {e}")
            print(f"Stderr from vwap_setup.py: {e.stderr}")
            print(f"Stdout from vwap_setup.py: {e.stdout}")
            sys.exit(1)
    elif app_choice == "2":
        print("\n--- You selected VOTER. (Further actions for VOTER not implemented yet.) ---")
        print("VOTER demo application setup is not yet implemented.")
    else:
        print("Invalid choice. Please enter 1 or 2.")
        sys.exit(1)

    print("\nMain script execution complete.")

if __name__ == "__main__":
    main()
