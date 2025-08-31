import sys
import argparse
from kubernetes_local_proxy import KubernetesLocalProxy
from manager_remote import deploy_manager, download_logs_remote

def run_scenario_batch(args):
    """Run a batch of scenarios using the scenario runner"""
    try:
        proxy = KubernetesLocalProxy(
            namespace=args.namespace,
            kubectl_context=args.kubectl_context,
            auto_deploy=False
        )

        runner_id = proxy.start_scenario_runner(
            scenario_dir=args.scenario_dir,
            engine=args.engine,
            image_prefix=args.image_prefix,
            cleanup_wait=args.cleanup_wait
        )

        print(f"✓ Scenario runner started with ID: {runner_id}")
        print(f"  Scenario directory: {args.scenario_dir}")
        print(f"  Engine: {args.engine}")
        print(f"  Cleanup wait: {args.cleanup_wait}s")

        # Save runner ID
        with open(f".runner-{args.namespace}", "w") as f:
            f.write(runner_id)

        print(f"\nUseful commands:")
        print(f"  Check status:  manager-remote --namespace {args.namespace} runner-status")
        print(f"  Follow logs:   manager-remote --namespace {args.namespace} runner-logs -f")
        print(f"  Stop runner:   manager-remote --namespace {args.namespace} runner-stop")

    except Exception as e:
        print(f"Failed to start scenario runner: {e}", file=sys.stderr)
        return False
    return True


def runner_status(args):
    """Check scenario runner status"""
    try:
        proxy = KubernetesLocalProxy(
            namespace=args.namespace,
            kubectl_context=args.kubectl_context,
            auto_deploy=False
        )

        # Get runner ID
        runner_id = args.runner_id
        if not runner_id:
            try:
                with open(f".runner-{args.namespace}", "r") as f:
                    runner_id = f.read().strip()
            except FileNotFoundError:
                print("No runner ID provided and no saved ID found", file=sys.stderr)
                return False

        status = proxy.get_runner_status(runner_id)
        print(f"Runner status: {status['status']}")

        if 'current_status' in status and status['current_status']:
            current = status['current_status']
            print(f"\nCurrent progress:")
            print(f"  Scenario: {current.get('current_scenario', 'Unknown')}")
            print(f"  Completed: {current.get('completed', 0)}/{current.get('total', 0)}")
            print(f"  Last update: {current.get('timestamp', 'Unknown')}")

    except Exception as e:
        print(f"Failed to get runner status: {e}", file=sys.stderr)
        return False
    return True


def runner_logs(args):
    """Get scenario runner logs"""
    try:
        proxy = KubernetesLocalProxy(
            namespace=args.namespace,
            kubectl_context=args.kubectl_context,
            auto_deploy=False
        )

        # Get runner ID
        runner_id = args.runner_id
        if not runner_id:
            try:
                with open(f".runner-{args.namespace}", "r") as f:
                    runner_id = f.read().strip()
            except FileNotFoundError:
                print("No runner ID provided and no saved ID found", file=sys.stderr)
                return False

        proxy.tail_runner_logs(
            runner_id=runner_id,
            lines=args.lines,
            follow=args.follow
        )

    except KeyboardInterrupt:
        print("\n✓ Stopped following logs")
    except Exception as e:
        print(f"Failed to get runner logs: {e}", file=sys.stderr)
        return False
    return True


def runner_stop(args):
    """Stop a running scenario batch"""
    try:
        proxy = KubernetesLocalProxy(
            namespace=args.namespace,
            kubectl_context=args.kubectl_context,
            auto_deploy=False
        )

        # Get runner ID
        runner_id = args.runner_id
        if not runner_id:
            try:
                with open(f".runner-{args.namespace}", "r") as f:
                    runner_id = f.read().strip()
            except FileNotFoundError:
                print("No runner ID provided and no saved ID found", file=sys.stderr)
                return False

        result = proxy.stop_scenario_runner(runner_id)
        print(f"Stop result: {result}")

        if result['status'] == 'stop_signal_sent':
            print("✓ Stop signal sent to scenario runner")
            print("The runner will stop after the current simulation completes its cleanup")

    except Exception as e:
        print(f"Failed to stop runner: {e}", file=sys.stderr)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Remote Simulation Manager for Kubernetes",
        prog="manager-remote"
    )

    # Global arguments
    parser.add_argument("--namespace", type=str, default="coinjoin", help="Kubernetes namespace")
    parser.add_argument("--kubectl-context", type=str, help="Kubernetes context to use")

    subparsers = parser.add_subparsers(dest="command", title="commands", help="Available commands")

    # Deploy command (existing)
    deploy_parser = subparsers.add_parser("deploy", help="Deploy simulation manager to cluster")
    deploy_parser.add_argument("--image-prefix", type=str, default="", help="Image prefix/registry")


    # Download-logs command
    download_parser = subparsers.add_parser("download-logs", help="Download simulation logs")
    download_parser.add_argument("--sim-id", type=str, help="Simulation ID")
    download_parser.add_argument("--all-logs", action="store_true",
                                 help="Download all logs from the orchestrator")
    download_parser.add_argument("--destination", type=str, default="./logs_download",
                                 help="Local directory to save logs")


    # Deploy command (existing)
    batch_parser = subparsers.add_parser("run", help="Run a batch of scenarios")
    batch_parser.add_argument("--scenario-dir", type=str, required=True,
                              help="Directory containing scenarios (in container)")
    batch_parser.add_argument("--engine", type=str, choices=["joinmarket", "wasabi"],
                              default="joinmarket", help="Simulation engine")
    batch_parser.add_argument("--image-prefix", type=str, default="", help="Image prefix")
    batch_parser.add_argument("--cleanup-wait", type=int, default=90,
                              help="Seconds to wait after cleanup")

    # Runner-status command
    runner_status_parser = subparsers.add_parser("status", help="Check scenario runner status")
    runner_status_parser.add_argument("--runner-id", type=str, help="Runner ID")

    # Runner-logs command
    runner_logs_parser = subparsers.add_parser("logs", help="Get scenario runner logs")
    runner_logs_parser.add_argument("--runner-id", type=str, help="Runner ID")
    runner_logs_parser.add_argument("--lines", type=int, default=50, help="Number of lines")
    runner_logs_parser.add_argument("--follow", "-f", action="store_true", help="Follow logs")

    # Runner-stop command
    runner_stop_parser = subparsers.add_parser("stop", help="Stop scenario runner")
    runner_stop_parser.add_argument("--runner-id", type=str, help="Runner ID")


    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Route to appropriate function
    if args.command == "deploy":
        success = deploy_manager(args)
    elif args.command == "run":
        success = run_scenario_batch(args)
    elif args.command == "status":
        success = runner_status(args)
    elif args.command == "logs":
        success = runner_logs(args)
    elif args.command == "stop":
        success = runner_stop(args)
    elif args.command == "download-logs":
        success = download_logs_remote(args)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())