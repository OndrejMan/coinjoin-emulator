import json
import time
import subprocess
import tempfile
import os
import uuid

import backoff


class KubernetesLocalProxy:
    """
    Local driver that delegates operations to a remote orchestrator pod in Kubernetes.
    This allows local management while executing operations inside the cluster.
    """

    def __init__(self, namespace="coinjoin", orchestrator_pod=None, kubectl_context=None, auto_deploy=True, image_prefix=""):
        self.namespace = namespace
        self.orchestrator_pod = orchestrator_pod or "deployment/emulation-manager"
        self.kubectl_context = kubectl_context
        self.simulation_id = str(uuid.uuid4())[:8]
        self._kubectl_base_cmd = self._build_kubectl_cmd()

        if auto_deploy:
            self.deploy_manager(image_prefix=image_prefix)

        # Test connection to orchestrator
        self._test_connection()

    def _build_kubectl_cmd(self):
        """Build base kubectl command with context if provided"""
        cmd = ["kubectl"]
        if self.kubectl_context:
            cmd.extend(["--context", self.kubectl_context])
        return cmd

    @backoff.on_exception(backoff.expo, Exception, max_tries=5)
    def _test_connection(self):
        """Test connection to the orchestrator pod"""
        try:
            result = self._kubectl_exec(["echo", "connection_test"])
            if "connection_test" not in result:
                raise Exception("Unexpected response from orchestrator")
            print(f"✓ Connected to orchestrator in namespace {self.namespace}")
        except Exception as e:
            raise Exception(f"Failed to connect to orchestrator: {e}")

    def _kubectl_exec(self, cmd, input_data=None, capture_output=True):
        """Execute command in the orchestrator pod via kubectl exec"""
        full_cmd = self._kubectl_base_cmd + [
            "exec", "-n", self.namespace,
            self.orchestrator_pod, "--"
        ] + cmd

        try:
            if input_data:
                result = subprocess.run(
                    full_cmd,
                    input=input_data,
                    text=True,
                    capture_output=capture_output,
                    check=True
                )
            else:
                result = subprocess.run(
                    full_cmd,
                    text=True,
                    capture_output=capture_output,
                    check=True
                )
            return result.stdout if capture_output else None
        except subprocess.CalledProcessError as e:
            print(f"Command failed: {' '.join(full_cmd)}")
            print(f"Error: {e.stderr if hasattr(e, 'stderr') else str(e)}")
            raise


    def _orchestrator_cmd(self, manager_args, input_data=None):
        """Execute manager.py command in orchestrator with arguments"""
        cmd = [
                  "python", "manager.py",
                  "--driver", "kubernetes", "--in-cluster",
                  "--namespace", self.namespace, "--reuse-namespace"
              ] + manager_args

        return self._kubectl_exec(cmd, input_data)

    def start_scenario_runner(self, scenario_dir, engine="joinmarket", image_prefix="", cleanup_wait=90):
        """Start the scenario runner inside the orchestrator pod"""
        runner_id = str(uuid.uuid4())[:8]
        print(f"Starting scenario runner {runner_id} in orchestrator...")

        # The scenario directory should be a path inside the container
        runner_cmd = [
            "python", "scenario_runner.py",
            "--scenario_dir", scenario_dir,
            "--namespace", self.namespace,
            "--image-prefix", image_prefix,
            "--cleanup-wait", str(cleanup_wait),
            "--in-cluster"  # New flag we'll add
        ]

        # Create a dedicated directory for this runner
        background_cmd = self._kubectl_base_cmd + [
            "exec", "-n", self.namespace,
            self.orchestrator_pod, "--",
            "sh", "-c",
            f"""
            RUNNER_DIR=/tmp/scenario-runners/{runner_id}
            mkdir -p $RUNNER_DIR

            # Start the runner in background
            nohup {' '.join(runner_cmd)} > $RUNNER_DIR/output.log 2>&1 &
            RUNNER_PID=$!

            # Save runner metadata
            echo $RUNNER_PID > $RUNNER_DIR/pid
            echo '{{"status": "running", "runner_id": "{runner_id}", "scenario_dir": "{scenario_dir}", "start_time": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}}' > $RUNNER_DIR/status.json

            echo "Started scenario runner with PID: $RUNNER_PID"
            """
        ]

        subprocess.run(background_cmd, check=True)
        print(f"✓ Scenario runner {runner_id} started")
        return runner_id



    def start_simulation(self, scenario_path, engine="joinmarket", image_prefix=""):
        """Start simulation in orchestrator"""
        print(f"Starting simulation {self.simulation_id} in orchestrator...")

        manager_cmd = [
            "python", "manager.py",
            "--driver", "kubernetes",
            "--in-cluster",
            "--engine", engine,
            "run",
            "--namespace", self.namespace,
            "--reuse-namespace",
            "--image-prefix", image_prefix,
            "--scenario", scenario_path  # This is the path INSIDE the container
        ]

        background_cmd = self._kubectl_base_cmd + [
            "exec", "-n", self.namespace,
            self.orchestrator_pod, "--",
            "sh", "-c",
            f"""
                SIM_DIR=/tmp/simulations/{self.simulation_id}
                mkdir -p $SIM_DIR
                nohup {' '.join(manager_cmd)} > $SIM_DIR/output.log 2>&1 &
                echo $! > $SIM_DIR/pid
                echo '{{"status": "running", "pid": "'$!'"", "start_time": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'", "scenario": "{scenario_path}"}}' > $SIM_DIR/status.json
            """
        ]
        print(f"Running command: {' '.join(background_cmd)}")

        subprocess.run(background_cmd, check=True)
        print(f"✓ Simulation {self.simulation_id} started in background")

        return self.simulation_id

    def get_status(self, simulation_id=None):
        """Get detailed status of a simulation"""
        sim_id = simulation_id or self.simulation_id

        # Check if the simulation directory exists and get process status
        status_cmd = self._kubectl_base_cmd + [
            "exec", "-n", self.namespace,
            self.orchestrator_pod, "--",
            "sh", "-c",
            f"""
            SIM_DIR=/tmp/simulations/{sim_id}

            # Check if simulation directory exists
            if [ ! -d "$SIM_DIR" ]; then
                echo '{{"status": "not_found", "simulation_id": "{sim_id}"}}'
                exit 0
            fi

            # Read the PID and check if process is running
            if [ -f "$SIM_DIR/pid" ]; then
                PID=$(cat "$SIM_DIR/pid")
                if ps -p $PID > /dev/null 2>&1; then
                    # Process is running - update status
                    echo '{{"status": "running", "pid": "'$PID'", "simulation_id": "{sim_id}"}}'
                else
                    # Process finished - check exit status
                    if [ -f "$SIM_DIR/exit_status" ]; then
                        EXIT_CODE=$(cat "$SIM_DIR/exit_status")
                        if [ "$EXIT_CODE" = "0" ]; then
                            echo '{{"status": "completed", "exit_code": 0, "simulation_id": "{sim_id}"}}'
                        else
                            echo '{{"status": "failed", "exit_code": '$EXIT_CODE', "simulation_id": "{sim_id}"}}'
                        fi
                    else
                        # Process ended but no exit status recorded
                        echo '{{"status": "terminated", "simulation_id": "{sim_id}"}}'
                    fi
                fi
            else
                echo '{{"status": "error", "message": "No PID file found", "simulation_id": "{sim_id}"}}'
            fi
            """
        ]

        try:
            result = subprocess.run(status_cmd, capture_output=True, text=True, check=True)
            return json.loads(result.stdout.strip())
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            return {"status": "error", "message": str(e), "simulation_id": sim_id}


    def tail_logs(self, lines=50, follow=False, simulation_id=None):
        """
        Tail simulation logs.

        Args:
            lines: Number of lines to show
            follow: If True, keep streaming new lines (like tail -f)
            simulation_id: Which simulation to tail (defaults to current)
        """
        sim_id = simulation_id or self.simulation_id

        if follow:
            # This will keep the connection open and stream logs
            tail_cmd = [
                "tail", "-f", f"/tmp/simulations/{sim_id}/output.log"
            ]

            # Use stream for real-time output
            print(f"Streaming logs for simulation {sim_id} (Ctrl+C to stop)...")
            try:
                # This is a blocking call that streams output
                subprocess.run(
                    self._kubectl_base_cmd + ["exec", "-n", self.namespace,
                                              self.orchestrator_pod, "--"] + tail_cmd,
                    check=True
                )
            except KeyboardInterrupt:
                print("\nStopped streaming logs")
        else:
            # Just get the last N lines
            tail_cmd = self._kubectl_base_cmd + [
                "exec", "-n", self.namespace,
                self.orchestrator_pod, "--",
                "tail", f"-{lines}", f"/tmp/simulations/{sim_id}/output.log"
            ]

            result = subprocess.run(tail_cmd, capture_output=True, text=True)
            print(result.stdout)

    def get_runner_status(self, runner_id=None):
        """
        Get status of a scenario runner, including current scenario progress.
        """
        r_id = runner_id or getattr(self, 'runner_id', None)
        if not r_id:
            return {"status": "error", "message": "No runner ID provided"}

        status_cmd = self._kubectl_base_cmd + [
            "exec", "-n", self.namespace,
            self.orchestrator_pod, "--",
            "sh", "-c",
            f"""
            RUNNER_DIR=/tmp/scenario-runners/{r_id}

            if [ ! -d "$RUNNER_DIR" ]; then
                echo '{{"status": "not_found", "runner_id": "{r_id}"}}'
                exit 0
            fi

            # Check if process is running
            if [ -f "$RUNNER_DIR/pid" ]; then
                PID=$(cat "$RUNNER_DIR/pid")
                if ps -p $PID > /dev/null 2>&1; then
                    # Runner is active - get current scenario status
                    CURRENT_STATUS="{'{}'}"
                    if [ -f "/tmp/scenario-runner-status.json" ]; then
                        CURRENT_STATUS=$(cat /tmp/scenario-runner-status.json)
                    fi
                    echo '{{"status": "running", "pid": "'$PID'", "runner_id": "{r_id}", "current_status": '$CURRENT_STATUS'}}'
                else
                    # Runner finished
                    echo '{{"status": "completed", "runner_id": "{r_id}"}}'
                fi
            else
                echo '{{"status": "error", "message": "No PID file", "runner_id": "{r_id}"}}'
            fi
            """
        ]

        try:
            result = subprocess.run(status_cmd, capture_output=True, text=True, check=True)
            return json.loads(result.stdout.strip())
        except Exception as e:
            return {"status": "error", "message": str(e), "runner_id": r_id}

    def tail_runner_logs(self, lines=50, follow=False, runner_id=None):
        """
        Tail scenario runner logs.

        This shows the output from the scenario runner, which includes all simulation outputs.
        """
        r_id = runner_id or getattr(self, 'runner_id', None)
        if not r_id:
            print("No runner ID provided")
            return

        log_file = f"/tmp/scenario-runners/{r_id}/output.log"

        if follow:
            # Stream logs in real-time
            tail_cmd = ["tail", "-f", log_file]
            print(f"Streaming logs for scenario runner {r_id} (Ctrl+C to stop)...")

            try:
                subprocess.run(
                    self._kubectl_base_cmd + ["exec", "-n", self.namespace,
                                              self.orchestrator_pod, "--"] + tail_cmd,
                    check=True
                )
            except KeyboardInterrupt:
                print("\nStopped streaming logs")
        else:
            # Just show last N lines
            tail_cmd = self._kubectl_base_cmd + [
                "exec", "-n", self.namespace,
                self.orchestrator_pod, "--",
                "tail", f"-{lines}", log_file
            ]

            result = subprocess.run(tail_cmd, capture_output=True, text=True)
            print(result.stdout)

    def stop_scenario_runner(self, runner_id=None):
        """
        Stop a running scenario runner.

        This will stop the current simulation and prevent further scenarios from running.
        """
        r_id = runner_id or getattr(self, 'runner_id', None)
        if not r_id:
            return {"status": "error", "message": "No runner ID provided"}

        # Send SIGTERM to the scenario runner process
        stop_cmd = self._kubectl_base_cmd + [
            "exec", "-n", self.namespace,
            self.orchestrator_pod, "--",
            "sh", "-c",
            f"""
            RUNNER_DIR=/tmp/scenario-runners/{r_id}

            if [ -f "$RUNNER_DIR/pid" ]; then
                PID=$(cat "$RUNNER_DIR/pid")

                if ps -p $PID > /dev/null 2>&1; then
                    echo "Sending SIGTERM to scenario runner (PID: $PID)..."
                    kill -TERM $PID

                    # Update status
                    echo '{{"status": "stopping", "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}}' > $RUNNER_DIR/status.json

                    echo '{{"status": "stop_signal_sent", "pid": "'$PID'"}}'
                else
                    echo '{{"status": "not_running"}}'
                fi
            else
                echo '{{"status": "not_found"}}'
            fi
            """
        ]

        try:
            result = subprocess.run(stop_cmd, capture_output=True, text=True, check=True)
            return json.loads(result.stdout.strip())
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _get_orchestrator_pod_name(self):
        """Get the actual pod name from deployment"""
        if "deployment/" in self.orchestrator_pod:
            deployment_name = self.orchestrator_pod.split("/")[1]
            cmd = self._kubectl_base_cmd + [
                "get", "pods", "-n", self.namespace,
                "-l", f"app={deployment_name}",
                "-o", "jsonpath={.items[0].metadata.name}"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        else:
            return self.orchestrator_pod


    def stop_simulation(self, simulation_id=None, timeout=30):
        """Stop a running simulation gracefully"""
        sim_id = simulation_id or self.simulation_id

        stop_cmd = self._kubectl_base_cmd + [
            "exec", "-n", self.namespace,
            self.orchestrator_pod, "--",
            "sh", "-c",
            f"""
            SIM_DIR=/tmp/simulations/{sim_id}

            if [ -f "$SIM_DIR/pid" ]; then
                PID=$(cat "$SIM_DIR/pid")

                # First try graceful shutdown with SIGTERM
                if ps -p $PID > /dev/null 2>&1; then
                    echo "Sending SIGTERM to process $PID..."
                    kill -TERM $PID

                    echo '{{"status": "stopping"}}'
                else
                    echo '{{"status": "not_running"}}'
                fi
            else
                echo '{{"status": "not_found"}}'
            fi
            """
        ]

        result = subprocess.run(stop_cmd, capture_output=True, text=True, check=True)
        print(f"Stop command result: {result.stdout}")

    def download_logs(self, local_destination="./logs", all_logs=False):
        """
        Download logs from the orchestrator container to local machine.

        If all_logs is True, downloads the entire /app/logs directory.
        Otherwise, downloads the most recent top-level simulation directory.
        """
        print("Preparing to download logs from orchestrator...")

        if all_logs:
            logs_dir = "/app/logs"
            tar_name = "/tmp/logs-all.tar.gz"
            print("Downloading the entire /app/logs directory...")
        else:
            find_sim_logs_script = '''
            LOGS_DIR=$(find /app/logs -mindepth 1 -maxdepth 1 -type d | grep -E "[0-9]{4}-[0-9]{2}-[0-9]{2}" | sort -r | head -1)
            if [ -z "$LOGS_DIR" ]; then
                echo "ERROR: No simulation logs found"
                exit 1
            fi
            echo "LOGS_DIR:$LOGS_DIR"
            '''

            find_cmd = self._kubectl_base_cmd + [
                "exec", "-n", self.namespace,
                self.orchestrator_pod, "--",
                "sh", "-c", find_sim_logs_script
            ]

            result = subprocess.run(find_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print("Could not find simulation logs")
                return False

            logs_dir = None
            for line in result.stdout.split('\n'):
                if line.startswith("LOGS_DIR:"):
                    logs_dir = line.split(":", 1)[1]
                    break

            if not logs_dir:
                print("Could not determine logs directory")
                return False

            print(f"Found logs directory: {logs_dir}")
            tar_name = "/tmp/logs-latest.tar.gz"

        tar_script = f'''
        TAR_FILE="{tar_name}"
        # Create archive while being tolerant to files changing during read
        # --warning=no-file-changed avoids non-zero exit when files are updated during archiving
        # --ignore-failed-read skips files that disappear mid-archive
        tar --warning=no-file-changed --ignore-failed-read -czf "$TAR_FILE" -C "/" "{logs_dir.lstrip('/')}"
        if [ -f "$TAR_FILE" ]; then
            SIZE=$(ls -lh "$TAR_FILE" | awk '{{print $5}}')
            echo "Created archive: $TAR_FILE ($SIZE)"
        else
            echo "ERROR: Failed to create archive"
            exit 1
        fi
        '''

        tar_cmd = self._kubectl_base_cmd + [
            "exec", "-n", self.namespace,
            self.orchestrator_pod, "--",
            "sh", "-c", tar_script
        ]

        print("Creating archive of logs...")
        result = subprocess.run(tar_cmd, capture_output=True, text=True)
        print(result.stdout)

        if result.returncode != 0:
            print("Failed to create logs archive")
            return False

        local_tar = tar_name.replace("/tmp/", "/tmp/local-")
        print("Downloading archive via kubectl exec (streaming)...")

        exec_cat_cmd = self._kubectl_base_cmd + [
            "exec", "-n", self.namespace,
            self.orchestrator_pod, "--",
            "sh", "-c", f"cat {tar_name}"
        ]

        try:
            with open(local_tar, "wb") as f_out:
                subprocess.run(exec_cat_cmd, stdout=f_out, stderr=subprocess.PIPE, check=True)
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode(errors="ignore") if e.stderr else str(e)
            print(f"Failed to download archive: {err}")
            return False

        os.makedirs(local_destination, exist_ok=True)

        extract_cmd = ["tar", "-xzf", local_tar, "-C", local_destination]
        result = subprocess.run(extract_cmd, capture_output=True, text=True)

        if result.returncode == 0:
            print(f"✓ Logs extracted to {local_destination}")
            os.remove(local_tar)
            cleanup_cmd = self._kubectl_base_cmd + [
                "exec", "-n", self.namespace,
                self.orchestrator_pod, "--",
                "rm", "-f", tar_name
            ]
            subprocess.run(cleanup_cmd, capture_output=True)
            return True
        else:
            print(f"Failed to extract archive: {result.stderr}")
            return False

    def deploy_manager(self, image_prefix="", wait_ready=True):
        """
        Deploy the simulation manager/orchestrator to the cluster if not already present.

        Args:
            image_prefix: Image prefix/registry (e.g., "myregistry.io/project/")
            wait_ready: Wait for the deployment to be ready

        Returns:
            bool: True if deployment successful
        """
        deployment_name = "emulation-manager"
        manager_image = f"{image_prefix}emulator-manager"

        # # Check if deployment already exists
        # check_cmd = self._kubectl_base_cmd + [
        #     "get", "deployment", deployment_name,
        #     "-n", self.namespace,
        #     "--ignore-not-found=true"
        # ]
        #
        # result = subprocess.run(check_cmd, capture_output=True, text=True)
        # if deployment_name in result.stdout:
        #     print(f"✓ Manager deployment already exists in namespace {self.namespace}")
        #     return True

        print(f"Deploying simulation manager to namespace {self.namespace}...")

        # # Create namespace if it doesn't exist
        # ns_cmd = self._kubectl_base_cmd + [
        #     "create", "namespace", self.namespace,
        #     "--dry-run=client", "-o", "yaml"
        # ]
        # subprocess.run(ns_cmd + ["| kubectl apply -f -"], shell=True)

        # Check if pre-created manifests exist
        manifest_dir = "./containers/emulator-manager"
        deployment_file = os.path.join(manifest_dir, "deployment.yaml")

        if os.path.exists(deployment_file):
            # Use pre-created manifests
            print("Using pre-created manifests from containers/emulator-manager/...")

            # Update the image in deployment.yaml if needed
            if image_prefix:
                import yaml
                with open(deployment_file, 'r') as f:
                    deployment = yaml.safe_load(f)

                # Update image
                deployment['spec']['template']['spec']['containers'][0]['image'] = manager_image
                deployment['spec']['template']['spec']['containers'][0]['imagePullPolicy'] = 'Always'

                # Save updated deployment
                with open(deployment_file, 'w') as f:
                    yaml.dump(deployment, f, default_flow_style=False)

            # Apply all manifests
            manifest_files = [
                "role.yaml",
                "rolebinding.yaml",
                "serviceaccount.yaml",
                "deployment.yaml"
            ]

            for manifest in manifest_files:
                manifest_path = os.path.join(manifest_dir, manifest)
                if os.path.exists(manifest_path):
                    apply_cmd = self._kubectl_base_cmd + [
                        "apply", "-f", manifest_path,
                        "-n", self.namespace
                    ]
                    subprocess.run(apply_cmd, check=True)
                else:
                    print(f"Warning: {manifest} not found in {manifest_dir}")
