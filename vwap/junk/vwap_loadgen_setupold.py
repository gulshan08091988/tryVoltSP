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
            
def apply_yaml_with_namespace_override(yaml_path, namespace):
    """
    Splits the YAML content by '---' to handle multiple documents in one file,
    applies namespace override to each, and then applies them using kubectl.
    """
    print(f"Applying file '{os.path.basename(yaml_path)}' to namespace '{namespace}'...")
    
    temp_yaml_file = None
    try:
        # Read the original YAML content
        with open(yaml_path, 'r') as f:
            yaml_content = f.read()

        # Split into multiple documents if present
        documents = yaml_content.split('---')
        
        # Create a temporary file to write the modified YAML
        temp_yaml_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml')
        temp_yaml_path = temp_yaml_file.name

        for doc in documents:
            if not doc.strip(): # Skip empty documents
                continue
            
            # Use yq to override the namespace for the current document
            # yq doesn't process stdin directly for 'e' command without a file,
            # so we write each part to a temp file and process it.
            # A more robust way might be to parse with PyYAML and then use yq programmatically if possible.
            # For simplicity and sticking to shell commands for yq, we'll process the full file then.
            # The original `yq e '.metadata.namespace = \"{namespace}\"' {yaml_path}` is fine if it handles multi-doc,
            # but for safety, ensuring all parts get the namespace is key.
            # The current `yq e '.metadata.namespace = \"{namespace}\"' {yaml_path}` will apply to all docs in the file.
            
            # The original implementation `yq e '.metadata.namespace = \"{namespace}\"' {yaml_path}`
            # correctly applies to all documents in a multi-document YAML file.
            # So, the multiple document parsing logic here is redundant if yq handles it correctly.
            # Reverting to the simpler, effective approach.

            # Re-using the simpler, effective yq command from the original script
            yq_cmd = f"yq e '.metadata.namespace = \"{namespace}\"' {yaml_path}"
            yq_result = run_command(yq_cmd, exit_on_error=True)
            temp_yaml_file.write(yq_result)
        
        temp_yaml_file.close()
        
        run_command(f"kubectl apply -f {temp_yaml_path}", "Applying Kubernetes manifest with namespace override...", exit_on_error=True)
        
        print(f"Successfully applied '{os.path.basename(yaml_path)}' to namespace '{namespace}'.")
    finally:
        if temp_yaml_file and os.path.exists(temp_yaml_path):
            os.remove(temp_yaml_path)


# --- Main Installation Logic ---

def main():
    """
    Main function for deploying the VWAP load generator.
    """
    print("\n--- Starting VWAP Load Generator setup ---")

    # Get namespace from command-line arguments (passed from vwap_setup.py)
    if len(sys.argv) < 2:
        print("Error: Missing namespace argument.")
        print("Expected: vwap_loadgen_setup.py <namespace>")
        sys.exit(1)

    loadgen_ns = sys.argv[1]
    print(f"Received namespace details: Namespace='{loadgen_ns}'")

    # Prerequisite check for yq
    try:
        subprocess.run("yq --version", shell=True, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError:
        print("Error: 'yq' command not found. Please install yq to continue.")
        print("Installation instructions: https://github.com/mikefarah/yq#install")
        sys.exit(1)

    # Get file paths from user input
    default_config_path = "/Users/gulshansharma/Downloads/voltsptest1/vwap-loadgen-config.yaml"
    loadgen_config_path = get_user_input(f"Enter path to VWAP Loadgen Config YAML file", default=default_config_path)
    
    default_job_path = "/Users/gulshansharma/Downloads/voltsptest1/vwap-loadgen-job.yaml"
    loadgen_job_path = get_user_input(f"Enter path to VWAP Loadgen Job YAML file", default=default_job_path)

    # Check if local files exist before proceeding
    if not os.path.exists(loadgen_config_path):
        print(f"Error: Loadgen config file not found at {loadgen_config_path}")
        sys.exit(1)
    if not os.path.exists(loadgen_job_path):
        print(f"Error: Loadgen job file not found at {loadgen_job_path}")
        sys.exit(1)
    
    print("\n--- Deploying Load Generator Configuration ---")
    apply_yaml_with_namespace_override(loadgen_config_path, loadgen_ns)
    
    print("\n--- Deploying Load Generator Job ---")
    apply_yaml_with_namespace_override(loadgen_job_path, loadgen_ns)

    print("\nVWAP Load Generator setup completed. You can monitor the job with:")
    print(f"  kubectl get jobs -n {loadgen_ns}")
    print(f"  kubectl get pods -l app=vwap-loadgen -n {loadgen_ns}")

if __name__ == "__main__":
    main()
