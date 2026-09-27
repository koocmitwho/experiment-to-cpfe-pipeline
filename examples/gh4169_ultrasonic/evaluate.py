"""Nested specimen holdouts and author-test evaluation using the existing CPU MLP."""

import argparse
import copy
import csv
import json
from pathlib import Path

import numpy as np

from experiment_to_cpfe.datasets.hdf5 import read_hdf5
from experiment_to_cpfe.datasets.training import run_dataset_build
from experiment_to_cpfe.learning.surrogate import predict_mlp, run_training
from experiment_to_cpfe.mechanics.tensile import regression_metrics


PAIRS = [[f"NO.{i}", f"NO.{i+4}"] for i in range(1, 5)]
ALPHAS = [.01, .1, 1., 10., 100.]


def protocol():
    outer = []
    for held_pair in PAIRS:
        inner = []
        for validation_pair in PAIRS:
            if validation_pair == held_pair:
                continue
            train = [x for pair in PAIRS if pair != held_pair and pair != validation_pair for x in pair]
            inner.append({"train": train, "validation": validation_pair.copy(), "test": held_pair.copy()})
        outer.append({"test": held_pair.copy(), "inner": inner})
    final = [{"train": [x for pair in PAIRS if pair != val for x in pair],
              "validation": val.copy(), "test": ["T1", "T2"]} for val in PAIRS]
    return {"outer": outer, "final": final}


def linear_predict(x_train, y_train, x_eval, *, alpha):
    mean = x_train.mean(axis=0)
    scale = x_train.std(axis=0)
    scale = np.where(scale > 1e-12, scale, 1.)
    x = (x_train-mean)/scale
    ymean = float(y_train.mean())
    # Augmented least squares supports singular/collinear inputs and alpha=0.
    lhs = np.vstack([x, np.sqrt(alpha)*np.eye(x.shape[1])])
    rhs = np.concatenate([y_train-ymean, np.zeros(x.shape[1])])
    coefficient = np.linalg.lstsq(lhs, rhs, rcond=None)[0]
    prediction = (x_eval-mean)/scale@coefficient+ymean
    return prediction, {"alpha": alpha, "x_mean": mean.tolist(), "x_scale": scale.tolist(),
                        "coefficient": coefficient.tolist(), "intercept": ymean}


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def evaluate(normalized_dir, output_dir, *, training_overrides=None):
    normalized, output = Path(normalized_dir).resolve(), Path(output_dir).resolve()
    template = json.loads((normalized/"build.json").read_text(encoding="utf-8"))
    identities = [item["sample_id"] for item in template["inputs"]]
    expected = [f"NO.{i}" for i in range(1, 9)] + ["T1", "T2"]
    if identities != expected:
        raise ValueError("evaluation requires the reviewed ten specimen identities in original order")
    settings = json.loads(Path(__file__).with_name("model.json").read_text(encoding="utf-8"))
    settings.update(training_overrides or {})
    design = protocol()
    output.mkdir(parents=True, exist_ok=False)
    _write(output/"protocol.json", {**design, "model": settings, "ridge_alphas": ALPHAS,
                                  "pair_rule": "original sample number i paired with i+4; fixed before fitting",
                                  "mlp_prediction": "equal-weight mean of validation-selected checkpoints"})
    features = [q["name"] for q in template["features"]]
    target = template["target"]["name"]
    rows = [read_hdf5(normalized/item["path"]).tables["measured_observations"][0] for item in template["inputs"]]
    x = np.array([[row[k] for k in features] for row in rows], float)
    y = np.array([row[target] for row in rows], float)
    index = {identity: i for i, identity in enumerate(identities)}
    predictions, model_receipts, baseline_receipts = [], [], []
    readback_error = 0.

    def indices(names):
        return [index[name] for name in names]

    def record_predictions(stage, model, names, values):
        for name, value in zip(names, values):
            i = index[name]
            predictions.append({"stage": stage, "model": model, "specimen": name,
                                "source_sheet": rows[i]["source_sheet"], "source_row": rows[i]["source_row"],
                                "target": float(y[i]), "prediction": float(value), "error": float(value-y[i]),
                                "absolute_error": float(abs(value-y[i])), "unit": "um"})

    def fit_fold(fold, name):
        nonlocal readback_error
        memberships = {identity: split for split, members in fold.items() for identity in members}
        if sum(map(len, fold.values())) != len(memberships):
            raise ValueError("overlapping specimen splits")
        config = copy.deepcopy(template)
        config["inputs"] = [{**item, "path": str(normalized/item["path"]), "split": memberships[item["sample_id"]]}
                            for item in config["inputs"] if item["sample_id"] in memberships]
        folder = output/name
        folder.mkdir(parents=True)
        _write(folder/"build.json", config)
        run_dataset_build(folder/"build.json", folder/"dataset")
        train_config = json.loads((folder/"dataset/training-config.json").read_text(encoding="utf-8"))
        train_config.update(settings)
        train_config["dataset"] = str(folder/"dataset/dataset.npz")
        _write(folder/"fit.json", train_config)
        run_training(folder/"fit.json", folder/"model")
        with np.load(folder/"model/predictions.npz", allow_pickle=False) as saved:
            readback = predict_mlp(folder/"model/model.pt", saved["features"])
            error = float(np.max(np.abs(readback-saved["prediction"])))
            if error > 1e-12:
                raise ValueError("checkpoint readback differs from saved predictions")
            readback_error = max(readback_error, error)
            by_group = dict(zip(saved["groups"].tolist(), readback.tolist()))
        training = json.loads((folder/"model/training.json").read_text(encoding="utf-8"))
        model_receipts.append({"path": str(folder/"model/model.pt"), "split": fold,
                               "best_epoch": training["best_epoch"], "epochs_completed": training["epochs_completed"],
                               "first_train_loss": training["history"][0]["train_mse_standardized"],
                               "last_train_loss": training["history"][-1]["train_mse_standardized"],
                               "normalization": training["normalization"]})
        return np.array([by_group[identity] for identity in fold["test"]])

    def baselines(stage, train_names, validation_folds, test_names):
        train, test = indices(train_names), indices(test_names)
        losses = []
        for alpha in ALPHAS:
            errors = []
            for fold in validation_folds:
                fit, val = indices(fold["train"]), indices(fold["validation"])
                pred, _ = linear_predict(x[fit], y[fit], x[val], alpha=alpha)
                errors.extend((pred-y[val]).tolist())
            losses.append(float(np.mean(np.square(errors))))
        chosen = ALPHAS[int(np.argmin(losses))]
        record_predictions(stage, "mean", test_names, np.full(len(test), y[train].mean()))
        for model, alpha in [("ols", 0.), ("ridge", chosen)]:
            pred, receipt = linear_predict(x[train], y[train], x[test], alpha=alpha)
            record_predictions(stage, model, test_names, pred)
            baseline_receipts.append({"stage": stage, "test": test_names, "train": train_names,
                                      "model": model, **receipt,
                                      "selection": {"alphas": ALPHAS, "validation_mse": losses} if model == "ridge" else None})

    for i, outer in enumerate(design["outer"]):
        values = [fit_fold(fold, f"outer-{i}/inner-{j}") for j, fold in enumerate(outer["inner"])]
        record_predictions("nested_development", "mlp", outer["test"], np.mean(values, axis=0))
        train_names = [name for name in expected[:8] if name not in outer["test"]]
        baselines("nested_development", train_names, outer["inner"], outer["test"])
    # External test targets never select features, pairs, settings, weights or alpha.
    final = [fit_fold(fold, f"final-{i}") for i, fold in enumerate(design["final"])]
    record_predictions("author_test", "mlp", ["T1", "T2"], np.mean(final, axis=0))
    baselines("author_test", expected[:8], design["final"], ["T1", "T2"])
    metrics = {}
    for stage in ("nested_development", "author_test"):
        metrics[stage] = {}
        for model in ("mlp", "mean", "ols", "ridge"):
            selected = [r for r in predictions if r["stage"] == stage and r["model"] == model]
            metrics[stage][model] = regression_metrics([r["target"] for r in selected], [r["prediction"] for r in selected])
    result = {"metrics": metrics, "predictions": predictions, "readback_max_abs_error": readback_error,
              "models": model_receipts, "baselines": baseline_receipts, "target_unit": "um",
              "normalization_manifest": str(normalized/"normalization.json"),
              "limitations": ["10 specimen summaries from one published study",
                              "8 nested development predictions and 2 author test predictions",
                              "outer MLP members fit 4 specimens; final members fit 6; baselines refit on 6/8",
                              "features retain the published specimen-level summaries",
                              "pre-existing author test identities retained; both test labels were public before this work",
                              "CC-BY-NC-3.0 applies to the real data and retained derived artifacts"]}
    _write(output/"evaluation.json", result)
    with (output/"predictions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--normalized-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(args.normalized_dir, args.output_dir)
    print(json.dumps(result["metrics"], indent=2))
