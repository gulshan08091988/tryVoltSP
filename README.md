
This comprehensive README.md provides a detailed guide for setting up and deploying the VWAP (Volume Weighted Average Price) demo application on Google Kubernetes Engine (GKE) using VoltDB, VoltSP, and Redpanda.

**VWAP Demo Deployment on GKE**
This repository contains Python scripts to automate the deployment of a Volume Weighted Average Price (VWAP) demo application on Google Kubernetes Engine (GKE). The demo leverages Redpanda as a Kafka-compatible streaming platform, VoltDB as the high-performance operational database, and VoltSP for streaming data processing.

**Table of Contents
**
Overview

Prerequisites

Directory Structure

Deployment Steps

1. Initialize the GKE Cluster

2. Deploy Redpanda

3. Deploy VoltDB Core

4. Deploy VoltSP Pipeline

5. Deploy VWAP Load Generator

Monitoring and Verification

Troubleshooting

**Overview**
The VWAP demo simulates real-time stock trading data processing.

The deployment process is orchestrated by a main Python script (tryVoltSP.py) which calls sub-scripts for each component:

***tryVoltSP.py***: The primary entry point. Handles GKE cluster creation/selection and orchestrates the deployment of Redpanda, VoltDB, VoltSP, and the VWAP load generator.

***vwap_setup.py***: Manages the deployment of the Redpanda cluster on GKE using Helm. It also configures the necessary Kafka topic (ticker-data).

***voltdb_core_setup.py***: Installs and configures the VoltDB Core cluster using its Helm chart. It handles Docker registry secrets, VoltDB license, DDL, and application JAR deployment. It also inserts a dummy record to verify VoltDB connectivity.

***voltsp_setup.py***: Deploys the VoltSP streaming pipeline, which reads data from Redpanda (Kafka) and writes it to VoltDB. This involves deploying a custom JAR and configuring the VoltSP application.

***vwap_loadgen_setup.py***: Deploys a Kubernetes Job that acts as a load generator, producing simulated ticker data into the Redpanda ticker-data topic.

**Prerequisites**
Before running the deployment scripts, ensure you have the following installed and configured:

Google Cloud SDK (gcloud): Authenticated and configured with your GCP project.

Install: https://cloud.google.com/sdk/docs/install

Authenticate: gcloud auth login

kubectl: Configured to interact with your Kubernetes clusters. (Usually installed with Google Cloud SDK).

helm (v3+): The Kubernetes package manager.

Install: https://helm.sh/docs/intro/install/

python3: The scripting language.

Ensure python3 and pip are in your PATH.

yq (version 4.x): A lightweight and portable command-line YAML processor. This is used by vwap_loadgen_setup.py for dynamic YAML modifications.

Install: https://github.com/mikefarah/yq#install

Docker Hub Account: Required for pulling VoltDB and VoltSP images. You'll need your Docker username and password.

VoltDB License XML File: A valid license.xml file for VoltDB. A placeholder license.xml is expected at vwap/license/license.xml.

VoltDB DDL File: The Data Definition Language (DDL) file for the VWAP schema. A placeholder vwap_ddl.sql is expected at vwap/ddl/vwap_ddl.sql.

VoltDB Application JAR: The compiled VoltDB application JAR (e.g., vwap_demo.jar). A placeholder vwap_demo.jar is expected at vwap/jars/vwap_demo.jar.

VoltSP Kafka Reader Stream JAR: The compiled VoltSP application JAR for reading from Kafka. A placeholder vwap-demo-1.0-SNAPSHOT-voltsp-kafka-reader-stream.jar is expected at vwap/jars/vwap-demo-1.0-SNAPSHOT-voltsp-kafka-reader-stream.jar.

**Directory Structure**
The project has the following structure:

tryvoltsp/
├── tryVoltSP.py                    # Main script to orchestrate deployment
└── vwap/
    ├── jars/                       # Contains VoltDB and VoltSP application JARs
    │   ├── vwap-demo-1.0-SNAPSHOT-voltsp-kafka-reader-stream.jar
    │   └── vwap_demo.jar
    ├── ddl/                        # Contains VoltDB DDL files
    │   └── vwap_ddl.sql
    ├── license/                    # Contains VoltDB license XML file
    │   └── license.xml
    ├── yaml/                       # Contains Kubernetes YAML templates
    │   └── vwap-loadgen-job.yaml
    ├── vwap_setup.py               # Script to deploy Redpanda
    ├── voltdb_core_setup.py        # Script to deploy VoltDB Core
    ├── voltsp_setup.py             # Script to deploy VoltSP
    └── vwap_loadgen_setup.py       # Script to deploy VWAP Load Generator
    
**Deployment Steps**

Follow these steps to deploy the VWAP demo. The main script tryVoltSP.py will guide you through the process, prompting for necessary inputs.

1. Initialize the GKE Cluster
The tryVoltSP.py script will first prompt you to set up or use an existing GKE cluster.

Run the main script:

Bash

python3 tryVoltSP.py
Enter "gke" when prompted for the action.

Provide your GCP Project ID.

Enter the GKE cluster name (default is voltsp).

If the cluster does not exist in the default zone (asia-northeast1-b), you'll be prompted to provide details for creating a new cluster (zone, version, number of nodes, machine type, disk size, disk type). If it exists, you'll be asked if you want to proceed with it.

Example for new cluster creation:

Enter your GCP Project ID: your-gcp-project-id
Setting gcloud project to your-gcp-project-id...
...
Enter the GKE cluster name (default: voltsp):
Checking if GKE cluster 'voltsp' exists in project 'your-gcp-project-id' and zone 'asia-northeast1-b'...
Cluster 'voltsp' does not exist in zone 'asia-northeast1-b'.
Please provide details to create a new GKE cluster.
Enter the GCP zone (default: asia-northeast1-b):
Enter the GKE cluster version (default: 1.32):
Enter the number of nodes (default: 6):
Enter the machine type (default: c2-standard-16):
Enter the disk size (GB) (default: 50):
Enter the disk type (default: pd-ssd):
Creating GKE cluster 'voltsp'...
The script will wait for the GKE cluster to be in the RUNNING state before proceeding.

2. Deploy Redpanda
After the GKE cluster is ready, the script will prompt you to select a demo application. Choose VWAP (Volume Weighted Average Price).

Select option 1 for VWAP when prompted.

Please select a demo application to proceed:
1) VWAP (Volume Weighted Average Price)
2) testdemo
Enter your choice (1 or 2): 1
The script will then execute vwap_setup.py to deploy Redpanda.

You will be asked for the Namespace for Redpanda (default is default) and the Redpanda Helm release name (default is redpanda-cluster).

The script will add and update the Redpanda Helm repository, install Redpanda (if not already existing), and wait for all Redpanda broker pods to become ready.

Example Output:

--- Starting Redpanda installation for VWAP demo ---
Adding Redpanda Helm repository...
Redpanda repository added successfully.
Updating Helm repositories...
Helm repositories updated.
Enter Namespace for Redpanda (default: default):
Ensuring namespace 'default' exists...
Creating or updating namespace 'default'...
Namespace 'default' is now ensured to exist.
Enter the Redpanda Helm release name (default: redpanda-cluster):
Checking if Helm release 'redpanda-cluster' already exists in namespace 'default'...
Helm release 'redpanda-cluster' does not exist in namespace 'default'. Installing it now.
Installing Redpanda...
...
All 3 Redpanda broker pods are ready.
Redpanda cluster is ready.
It will then configure the ticker-data topic in Redpanda.

3. Deploy VoltDB Core
Once Redpanda is set up, vwap_setup.py will call voltdb_core_setup.py to deploy VoltDB.

You will be prompted for the Namespace to install VoltDB Core (default is voltdb) and the VoltDB Cluster Name (default is volt-vwap).

You will be asked if you need to create a Docker registry secret for VoltDB Core. If yes, provide your Docker username, password, and optionally email. The secret will be named dockerio-registry.

Provide the VoltDB product version (e.g., 13.3.6, 14.1.0).

Confirm paths for the VoltDB license XML file, VoltDB DDL file, and VoltDB application JAR file. The script provides sensible defaults based on the vwap/ directory structure.

The script will install VoltDB Core using Helm and wait for its StatefulSet to become ready.

Finally, it will attempt to insert a dummy record into a DUMMY table in VoltDB to verify connectivity.

Example Output:

--- Starting VoltDB Core installation ---
...
Enter Namespace to install VoltDB Core (default: voltdb):
Ensuring namespace 'voltdb' exists...
...
Enter the VoltDB Cluster Name (default: volt-vwap):
...
Do you need to create/update a Docker registry secret for VoltDB Core? (yes/no) (default: yes):
...
Enter Docker Username: your_docker_username
Enter Docker Password:
...
Enter the VoltDB product version (default: 13.3.6):
Enter path to VoltDB license XML file (default: /path/to/tryvoltsp/vwap/license/license.xml):
Enter path to VoltDB DDL file (default: /path/to/tryvoltsp/vwap/ddl/vwap_ddl.sql):
Enter path to VoltDB application JAR file (e.g., vwap_demo.jar) (default: /path/to/tryvoltsp/vwap/jars/vwap_demo.jar):
Installing VoltDB Core...
...
VoltDB Core cluster is ready.
...
Dummy record 'X' inserted successfully.
VoltDB Core installation complete.
4. Deploy VoltSP Pipeline
After VoltDB Core is ready, voltdb_core_setup.py will call voltsp_setup.py to deploy the VoltSP pipeline.

You will be prompted for the VoltSP Pipeline Name (default pipeline1) and the Namespace to install VoltSP (default will be the same as VoltDB namespace, voltdb).

You will be asked if you need to create a Docker registry secret for VoltSP. If yes, provide your Docker credentials. The secret will be named voltsp-docker-registry-secret.

Confirm paths for the VoltSP license XML file and VoltSP Kafka Reader Stream JAR file. The script provides sensible defaults.

The script will dynamically generate the VoltSP configuration based on the deployed Redpanda and VoltDB service addresses.

It will then install the VoltSP pipeline using Helm and wait for its deployment to become ready.

Example Output:

--- Starting VoltSP pipeline installation ---
...
Enter the VoltSP Pipeline Name (default: pipeline1):
Enter Namespace to install VoltSP (default: voltdb):
Ensuring namespace 'voltdb' exists...
...
Do you need to create/update a Docker registry secret for VoltSP? (yes/no) (default: yes):
...
Dynamically generating VoltSP configuration...
  Generated Kafka bootstrapServers: redpanda-cluster.default.svc.cluster.local:9093
  Generated VoltDB sink servers: volt-vwap-voltdb-cluster-client.voltdb.svc.cluster.local:21212
...
Installing VoltSP pipeline...
...
VoltSP pipeline is ready.
VoltSP installation complete.
5. Deploy VWAP Load Generator
Finally, voltsp_setup.py will call vwap_loadgen_setup.py to deploy the load generator.

The script will use the same namespace as VoltSP for the load generator.

It will confirm the path to the VWAP Loadgen Job YAML file (default: vwap/yaml/vwap-loadgen-job.yaml).

The vwap-loadgen-config ConfigMap will be dynamically generated with the correct Redpanda and VoltDB service addresses and then applied.

The vwap-loadgen-job.yaml will be applied with the correct namespace override.

Example Output:

--- Starting VWAP Load Generator setup script... ---
Received Loadgen Namespace: 'voltdb'
Received Redpanda Namespace: 'default'
Received VoltDB Namespace: 'voltdb'
...
--- Dynamically Generating VWAP Loadgen ConfigMap ---
  Setting KAFKA_BROKER_ADDR to: redpanda-cluster.default.svc.cluster.local:9093
  Setting VOLTDB_SVC_ADDR to: volt-vwap-voltdb-cluster-client.voltdb.svc.cluster.local:21212
Applying dynamically generated ConfigMap...
...
Successfully deployed dynamically generated VWAP Loadgen ConfigMap.
--- Deploying Load Generator Job ---
Overriding namespace in vwap-loadgen-job.yaml using yq...
Applying Kubernetes Job manifest...
...
Successfully applied 'vwap-loadgen-job.yaml' to namespace 'voltdb'.
VWAP Load Generator setup completed. You can monitor the job with:
  kubectl get jobs -n voltdb
  kubectl get pods -l job-name=vwap-loadgen -n voltdb
The main script execution will then complete.

Monitoring and Verification
After deployment, you can verify the status of the components using kubectl:

GKE Cluster:

Bash

gcloud container clusters list
kubectl get nodes
Redpanda:

Bash

kubectl get pods -n <redpanda-namespace> -l app.kubernetes.io/name=redpanda
kubectl logs -n <redpanda-namespace> <redpanda-broker-pod-name>
kubectl exec -it <redpanda-broker-pod-name> -n <redpanda-namespace> -c redpanda -- rpk topic list
VoltDB Core:

Bash

kubectl get pods -n <voltdb-namespace> -l app=voltdb
kubectl get sts -n <voltdb-namespace>
kubectl logs -n <voltdb-namespace> <voltdb-pod-name>
kubectl exec -it <voltdb-pod-name> -n <voltdb-namespace> -- sqlcmd
VoltSP:

Bash

kubectl get pods -n <voltsp-namespace> -l app.kubernetes.io/instance=<voltsp-release-name>
kubectl get deploy -n <voltsp-namespace>
kubectl logs -n <voltsp-namespace> <voltsp-pod-name>
VWAP Load Generator:

Bash

kubectl get jobs -n <loadgen-namespace>
kubectl get pods -l job-name=vwap-loadgen -n <loadgen-namespace>
kubectl logs -f -n <loadgen-namespace> <vwap-loadgen-pod-name>
Cleanup
To clean up the deployed resources:

Uninstall Helm Releases:

Bash

helm uninstall <voltsp-release-name> -n <voltsp-namespace>
helm uninstall <volt-cluster-name> -n <voltdb-namespace>
helm uninstall <redpanda-release-name> -n <redpanda-namespace>
# If the loadgen was deployed as a Job, it will complete and its pods will exit.
# To remove the job itself:
kubectl delete job vwap-loadgen -n <loadgen-namespace>
kubectl delete configmap vwap-loadgen-config -n <loadgen-namespace>
Delete Namespaces (optional, but recommended for clean slate):

Bash

kubectl delete namespace <voltsp-namespace>
kubectl delete namespace <voltdb-namespace>
kubectl delete namespace <redpanda-namespace>
Delete GKE Cluster:

Bash

gcloud container clusters delete <gke-cluster-name> --zone <gke-cluster-zone> --project <gcp-project-id>
Note: Deleting the GKE cluster will remove all resources within it, including namespaces, pods, services, etc. This is the most complete cleanup method.

Troubleshooting
"command not found" for gcloud, kubectl, helm, or yq: Ensure these tools are installed and their executables are in your system's PATH.

gcloud authentication issues: Run gcloud auth login and gcloud config set project <your-project-id>.

Helm release already exists: The scripts include logic to detect existing Helm releases. If a release is in a bad state, you might need to manually uninstall it using helm uninstall <release-name> -n <namespace>.

Pod stuck in Pending state: Check kubectl describe pod <pod-name> -n <namespace> for events and reasons. Common issues include insufficient resources, missing PersistentVolumeClaims (PVCs), or incorrect image pull secrets.

ImagePullBackOff or ErrImagePull:

Ensure your Docker registry secret is correctly created and referenced in the Helm chart values.

Verify your Docker credentials are correct.

Confirm the image name and tag in the Helm chart values or Kubernetes manifests are correct and accessible.

CrashLoopBackOff: Check the logs of the crashing pod using kubectl logs <pod-name> -n <namespace>. This usually indicates an application-level error.

VoltDB or VoltSP not becoming Ready:

Check pod logs and describe commands as above.

Verify that the license file, DDL, and JARs are correctly mounted and accessible within the pods.

Ensure the voltdbVersion specified for VoltDB matches a supported version by the Helm chart and the downloaded images.

Network connectivity issues between components (e.g., VoltSP to Redpanda/VoltDB):

Verify that the service addresses generated (KAFKA_BROKER_ADDR, VOLTDB_SVC_ADDR) are correct and resolvable within the cluster.

Check Kubernetes Services: kubectl get svc -n <namespace>.

Use kubectl exec into a pod to try ping or nc to the service addresses/ports.

CalledProcessError in Python scripts: The scripts are designed to print the stdout and stderr of failed shell commands. Examine these outputs carefully for clues.
