#!/usr/bin/env python3
"""
Launch a HyperDrive hyperparameter sweep on Azure ML.

Explores XGBoost hyperparameters across a compute cluster and picks the
best configuration by ROC-AUC. Downloads the winning model artifacts
to models/trained/ for local use.

Prerequisites:
  - Azure ML workspace created (see deploy/azure-ml-setup.sh)
  - pip install azure-ai-ml mlflow azureml-mlflow

Usage:
  python scripts/aml_sweep.py                    # Launch sweep (36 trials)
  python scripts/aml_sweep.py --max-trials 100   # Larger sweep
  python scripts/aml_sweep.py --download-best     # Download best model from last sweep
"""

import os
import sys
import argparse
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Launch AML HyperDrive sweep")
    parser.add_argument("--max-trials", type=int, default=36,
                        help="Maximum number of hyperparameter combinations to try")
    parser.add_argument("--compute-name", type=str, default="cycling-sweep-cpu",
                        help="AML compute cluster name")
    parser.add_argument("--experiment-name", type=str, default="cycling-h2h-sweep",
                        help="MLflow experiment name")
    parser.add_argument("--download-best", action="store_true",
                        help="Download best model from latest sweep instead of launching new one")
    parser.add_argument("--wait", action="store_true", default=True,
                        help="Wait for sweep to complete (default: True)")
    return parser.parse_args()


def get_ml_client():
    """Connect to Azure ML workspace."""
    from azure.ai.ml import MLClient
    from azure.identity import DefaultAzureCredential

    # These can come from env vars or Azure CLI login
    subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID")
    resource_group = os.environ.get("AZURE_RESOURCE_GROUP", "cycling-predictor-rg")
    workspace_name = os.environ.get("AZURE_ML_WORKSPACE", "cycling-predictor-ml")

    if subscription_id:
        return MLClient(
            DefaultAzureCredential(),
            subscription_id=subscription_id,
            resource_group_name=resource_group,
            workspace_name=workspace_name,
        )
    else:
        # Fall back to config file or Azure CLI defaults
        return MLClient.from_config(credential=DefaultAzureCredential())


def launch_sweep(args):
    """Submit a HyperDrive sweep job to AML."""
    from azure.ai.ml import command, Input
    from azure.ai.ml.sweep import Choice, Uniform, LogUniform, BanditPolicy

    ml_client = get_ml_client()

    # Define the training command
    train_command = command(
        code=".",  # Upload entire repo
        command=(
            "python scripts/aml_train.py "
            "--n-estimators ${{inputs.n_estimators}} "
            "--max-depth ${{inputs.max_depth}} "
            "--learning-rate ${{inputs.learning_rate}} "
            "--subsample ${{inputs.subsample}} "
            "--colsample-bytree ${{inputs.colsample_bytree}} "
            "--min-child-weight ${{inputs.min_child_weight}} "
            "--reg-alpha ${{inputs.reg_alpha}} "
            "--reg-lambda ${{inputs.reg_lambda}} "
            "--gamma ${{inputs.gamma}} "
            "--calibration-method ${{inputs.calibration_method}} "
        ),
        environment="cycling-predictor-env@latest",
        compute=args.compute_name,
        experiment_name=args.experiment_name,
        display_name="cycling-h2h-sweep",
    )

    # Define the sweep space
    sweep_job = train_command.sweep(
        sampling_algorithm="bayesian",
        primary_metric="roc_auc",
        goal="maximize",
        max_total_trials=args.max_trials,
        max_concurrent_trials=4,
        # Early termination: stop poor runs after 10 trials
        early_termination=BanditPolicy(
            evaluation_interval=1,
            slack_factor=0.1,
            delay_evaluation=10,
        ),
    )

    # Hyperparameter search space
    sweep_job.set_limits(timeout=7200)  # 2 hour max

    sweep_job.inputs = {
        "n_estimators": Choice(values=[200, 300, 500, 800]),
        "max_depth": Choice(values=[4, 6, 8, 10, 12]),
        "learning_rate": LogUniform(min_value=-4, max_value=-1),  # ~0.0001 to 0.1
        "subsample": Uniform(min_value=0.6, max_value=1.0),
        "colsample_bytree": Uniform(min_value=0.5, max_value=1.0),
        "min_child_weight": Choice(values=[1, 5, 10, 20, 50]),
        "reg_alpha": LogUniform(min_value=-5, max_value=2),  # ~0.00001 to 100
        "reg_lambda": LogUniform(min_value=-3, max_value=2),  # ~0.001 to 100
        "gamma": Uniform(min_value=0.0, max_value=5.0),
        "calibration_method": Choice(values=["isotonic", "sigmoid"]),
    }

    log.info(f"Submitting sweep with up to {args.max_trials} trials...")
    submitted_job = ml_client.jobs.create_or_update(sweep_job)
    log.info(f"Sweep job submitted: {submitted_job.name}")
    log.info(f"Studio URL: {submitted_job.studio_url}")

    if args.wait:
        log.info("Waiting for sweep to complete (this may take 1-2 hours)...")
        ml_client.jobs.stream(submitted_job.name)
        log.info("Sweep complete!")

        # Download best model
        _download_best_from_job(ml_client, submitted_job.name)


def _download_best_from_job(ml_client, job_name):
    """Download artifacts from the best trial of a sweep."""
    job = ml_client.jobs.get(job_name)

    # Get best trial
    best_child_run_id = job.properties.get("best_child_run_id")
    if not best_child_run_id:
        log.warning("No best child run found — check the sweep in Azure ML Studio")
        return

    output_dir = os.path.join("models", "trained")
    os.makedirs(output_dir, exist_ok=True)

    log.info(f"Downloading best model from trial {best_child_run_id}...")
    ml_client.jobs.download(
        best_child_run_id,
        download_path=output_dir,
        output_name="default",
    )

    # Move artifacts from nested output structure to models/trained/
    nested = os.path.join(output_dir, "named-outputs", "default", "outputs")
    if os.path.isdir(nested):
        import shutil
        for fname in os.listdir(nested):
            src = os.path.join(nested, fname)
            dst = os.path.join(output_dir, fname)
            shutil.move(src, dst)
            log.info(f"  → {dst}")
        shutil.rmtree(os.path.join(output_dir, "named-outputs"), ignore_errors=True)

    log.info(f"Best model downloaded to {output_dir}/")

    # Print the winning hyperparameters
    metrics_path = os.path.join(output_dir, "sweep_metrics.json")
    if os.path.exists(metrics_path):
        import json
        with open(metrics_path) as f:
            metrics = json.load(f)
        log.info(f"Best metrics: AUC={metrics.get('roc_auc', '?'):.4f}  "
                 f"Brier={metrics.get('brier_score', '?'):.4f}  "
                 f"Acc={metrics.get('accuracy', '?'):.4f}")


def download_best(args):
    """Download the best model from the latest sweep."""
    ml_client = get_ml_client()

    # Find latest sweep job
    jobs = ml_client.jobs.list(
        experiment_name=args.experiment_name,
    )
    sweep_jobs = [j for j in jobs if j.type == "sweep"]
    if not sweep_jobs:
        log.error(f"No sweep jobs found in experiment '{args.experiment_name}'")
        return

    latest = sorted(sweep_jobs, key=lambda j: j.creation_context.created_at)[-1]
    log.info(f"Latest sweep: {latest.name} ({latest.status})")
    _download_best_from_job(ml_client, latest.name)


def main():
    args = parse_args()
    if args.download_best:
        download_best(args)
    else:
        launch_sweep(args)


if __name__ == "__main__":
    main()
