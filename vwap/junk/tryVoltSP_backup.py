import subprocess
import sys
import os

# --- Helper Functions (MUST BE DEFINED BEFORE main() uses them) ---

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
    # Use --format 'value(name)' to get just the cluster name if it exists, otherwise empty
    command = f"gcloud container clusters list --project {project_id} --filter='name={cluster_name} AND zone={zone}' --format='value(name)'"
    try:
        output = subprocess.run(command, shell=True, check=False, text=True, capture_output=True).stdout.strip()
        return output == cluster_name
    except Exception as e:
        print(f"An error occurred while checking cluster existence: {e}")
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

    # 3. Check for existing cluster right after getting the name
    # We will assume the default zone for the initial check to see if it exists
    # If the user wants to specify a different zone, that will come later if we create a new cluster
    
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
            # If proceeding with existing, we don't need to ask for creation parameters
            # and we use the default_gcp_zone which is now confirmed as its zone
            pass # Continue to get-credentials part
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

    # Regardless of whether it's new or existing, get credentials for the cluster
    run_command(f"gcloud container clusters get-credentials {gke_cluster_name} --zone {gcp_zone} --project {gcp_project_id}",
                "Configuring kubectl to connect to the GKE cluster...")

    print("\nGKE cluster is ready.")

    # --- Demo Application Selection ---
    print("\nPlease select a demo application to proceed:")
    print("1) VWAP (Volume Weighted Average Price)")
    print("2) VOTER")

    app_choice = get_user_input("Enter your choice (1 or 2): ")

    if app_choice == "1":
        print("\n--- You selected VWAP. Starting VWAP setup script (Redpanda & VoltDB & VoltSP)... ---")
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
