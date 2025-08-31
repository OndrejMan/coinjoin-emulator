#!/usr/bin/env python3
"""
JoinMarket Scenario Runner
Runs all scenarios in a given folder with proper cleanup and error handling
"""

import os
import subprocess
import time
import json
import argparse
from datetime import datetime
from typing import List, Tuple, Optional


class ScenarioRunner:
    def __init__(self,
                 scenario_dir: str,
                 namespace: str = "rajnoha-ns",
                 image_prefix: str = "drajnoha/",
                 proxy: str = "socks5://127.0.0.1:8123",
                 shadowsocks_config: str = "/home/drajnoha/Code/PycharmProjects/coinjoin-simulator/shadowsocks/config_local.yaml",
                 cleanup_wait: int = 150,
                 in_cluster: bool = False):

        self.scenario_dir = scenario_dir
        self.namespace = namespace
        self.image_prefix = image_prefix
        self.proxy = proxy
        self.shadowsocks_config = shadowsocks_config
        self.cleanup_wait = cleanup_wait
        self.sslocal_process = None
        self.results = []
        self.in_cluster = in_cluster
        self.current_scenario_file = None


    def _write_current_status(self):
        """Write current status to a file for external monitoring"""
        if self.in_cluster:
            status = {
                "current_scenario": self.current_scenario_file,
                "timestamp": self.get_timestamp(),
                "completed": len([r for r in self.results if r.get("success", False)]),
                "total": len(self.results)
            }
            # Write to a known location in the container
            with open("/tmp/scenario-runner-status.json", "w") as f:
                json.dump(status, f)

    def cleanup_kubernetes(self) -> bool:
        """Clean up kubernetes resources"""
        print(f"[{self.get_timestamp()}] Cleaning up kubernetes resources...")

        cmd = [
            "python", "manager.py",
            "--driver", "kubernetes",
            "--engine", "joinmarket",
            "clean",
            "--reuse-namespace",
            "--namespace", self.namespace,
            "--image-prefix", self.image_prefix
        ]

        if self.in_cluster:
            cmd.insert(4, "--in-cluster")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if result.returncode == 0:
                print(f"[{self.get_timestamp()}] Cleanup successful, waiting {self.cleanup_wait} seconds...")
                time.sleep(self.cleanup_wait)
                return True
            else:
                print(f"[{self.get_timestamp()}] ERROR: Cleanup failed")
                print(f"STDOUT: {result.stdout}")
                print(f"STDERR: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            print(f"[{self.get_timestamp()}] ERROR: Cleanup timed out after 5 minutes")
            return False
        except Exception as e:
            print(f"[{self.get_timestamp()}] ERROR during cleanup: {e}")
            return False

    def run_scenario(self, scenario_file: str) -> Tuple[bool, float]:
        """Run a single scenario"""
        print(f"\n[{self.get_timestamp()}] Running scenario: {scenario_file}")
        self.current_scenario_file = scenario_file
        self._write_current_status()


        cmd = [
            "python", "manager.py",
            "--driver", "kubernetes",
            "--engine", "joinmarket",
            "run",
            "--namespace", self.namespace,
            "--reuse-namespace",
            "--image-prefix", self.image_prefix,
            "--scenario", scenario_file
        ]

        if self.in_cluster:
            cmd.insert(4, "--in-cluster")

        if not self.in_cluster and self.proxy:
            cmd.extend(["--proxy", self.proxy])

        start_time = time.time()

        try:
            # Run the scenario
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            # Stream output in real-time
            for line in iter(process.stdout.readline, ''):
                if line:
                    print(f"  {line.rstrip()}")

            # Wait for completion
            return_code = process.wait()
            duration = time.time() - start_time

            if return_code == 0:
                print(f"[{self.get_timestamp()}] SUCCESS: Scenario completed in {duration:.1f} seconds")
                return True, duration
            else:
                stderr = process.stderr.read()
                print(f"[{self.get_timestamp()}] ERROR: Scenario failed after {duration:.1f} seconds")
                print(f"STDERR: {stderr}")
                return False, duration

        except Exception as e:
            duration = time.time() - start_time
            print(f"[{self.get_timestamp()}] ERROR running scenario: {e}")
            return False, duration

    def get_scenarios(self) -> List[str]:
        """Get all JSON scenario files in the directory"""
        scenarios = []

        for root, dirs, files in os.walk(self.scenario_dir):
            for file in files:
                if file.endswith('.json'):
                    scenarios.append(os.path.join(root, file))

        return sorted(scenarios)

    def get_timestamp(self) -> str:
        """Get current timestamp for logging"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def save_results(self):
        """Save run results to file"""
        results_file = os.path.join('logs', f"run_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

        with open(results_file, 'w') as f:
            json.dump(self.results, f, indent=2)

        print(f"\nResults saved to: {results_file}")

    def run_all(self, start_from: Optional[str] = None):
        """Run all scenarios with proper error handling"""
        scenarios = self.get_scenarios()

        if not scenarios:
            print(f"No scenarios found in {self.scenario_dir}")
            return

        print(f"Found {len(scenarios)} scenarios to run")

        # Skip scenarios if start_from is specified
        start_index = 0
        if start_from:
            for i, scenario in enumerate(scenarios):
                if start_from in scenario:
                    start_index = i
                    print(f"Starting from scenario: {scenario}")
                    break

        try:
            # Initial cleanup
            print("\nPerforming initial cleanup...")
            self.cleanup_kubernetes()

            # Run each scenario
            for i, scenario in enumerate(scenarios[start_index:], start=start_index):
                print(f"\n{'=' * 80}")
                print(f"Scenario {i + 1}/{len(scenarios)}: {os.path.basename(scenario)}")
                print(f"{'=' * 80}")

                # Try to run the scenario
                success, duration = self.run_scenario(scenario)

                self.results.append({
                    "scenario": scenario,
                    "success": success,
                    "duration": duration,
                    "timestamp": self.get_timestamp()
                })

                # If failed, try cleanup and retry once
                if not success:
                    print(f"\n[{self.get_timestamp()}] Scenario failed, attempting cleanup and retry...")

                    if self.cleanup_kubernetes():
                        print(f"[{self.get_timestamp()}] Retrying scenario...")
                        success, duration = self.run_scenario(scenario)

                        self.results[-1]["retry"] = True
                        self.results[-1]["retry_success"] = success
                        self.results[-1]["retry_duration"] = duration

                        if not success:
                            print(f"[{self.get_timestamp()}] Scenario failed on retry, continuing to next...")
                    else:
                        print(f"[{self.get_timestamp()}] Cleanup failed, skipping retry")

                # Clean up after each scenario
                if i < len(scenarios) - 1:  # Don't cleanup after last scenario
                    print(f"\n[{self.get_timestamp()}] Cleaning up before next scenario...")
                    self.cleanup_kubernetes()

                # Save intermediate results
                self.save_results()

        except KeyboardInterrupt:
            print(f"\n[{self.get_timestamp()}] Interrupted by user")
        finally:
            # Final cleanup
            print(f"\n[{self.get_timestamp()}] Performing final cleanup...")
            self.cleanup_kubernetes()

            # Print summary
            print(f"\n{'=' * 80}")
            print("RUN SUMMARY")
            print(f"{'=' * 80}")

            successful = sum(1 for r in self.results if r["success"] or r.get("retry_success", False))
            failed = len(self.results) - successful

            print(f"Total scenarios: {len(self.results)}")
            print(f"Successful: {successful}")
            print(f"Failed: {failed}")

            if failed > 0:
                print("\nFailed scenarios:")
                for r in self.results:
                    if not r["success"] and not r.get("retry_success", False):
                        print(f"  - {os.path.basename(r['scenario'])}")

            # Save final results
            self.save_results()


def main():
    parser = argparse.ArgumentParser(description="Run JoinMarket scenarios")
    parser.add_argument("--scenario_dir", help="Directory containing scenario JSON files")
    parser.add_argument("--namespace", default="rajnoha-ns", help="Kubernetes namespace")
    parser.add_argument("--in-cluster", action="store_true", default="False", help="When scenario runner is running in cluster")
    parser.add_argument("--image-prefix", default="drajnoha/", help="Docker image prefix")
    parser.add_argument("--proxy", default="socks5://127.0.0.1:8123", help="Proxy URL")
    parser.add_argument("--shadowsocks-config",
                        default="/home/drajnoha/Code/PycharmProjects/coinjoin-simulator/shadowsocks/config_local.yaml",
                        help="Shadowsocks config file")
    parser.add_argument("--cleanup-wait", type=int, default=90,
                        help="Seconds to wait after cleanup")
    parser.add_argument("--start-from", help="Start from scenario containing this string")

    args = parser.parse_args()

    runner = ScenarioRunner(
        scenario_dir=args.scenario_dir,
        namespace=args.namespace,
        image_prefix=args.image_prefix,
        proxy=args.proxy,
        shadowsocks_config=args.shadowsocks_config,
        cleanup_wait=args.cleanup_wait,
        in_cluster=args.in_cluster
    )

    runner.run_all(start_from=args.start_from)


if __name__ == "__main__":
    main()