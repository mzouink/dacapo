from dacapo.store import MongoDbStore
from dacapo.tasks import Task
from dacapo.data import Data
from dacapo.train_pipeline import create_train_pipeline
from dacapo.training_stats import TrainingStats
from dacapo.validate import validate
from dacapo.validation_scores import ValidationScores
from tqdm import tqdm
import funlib.run
import gunpowder as gp
import hashlib
import numpy as np
import os
import time

import torch


class Run:
    def __init__(
        self,
        task_config,
        data_config,
        model_config,
        optimizer_config,
        repetition,
        validation_interval,
        snapshot_interval,
        keep_best_validation,
        billing=None,
        batch=False,
    ):

        # configs
        self.task_config = task_config
        self.data_config = data_config
        self.model_config = model_config
        self.optimizer_config = optimizer_config

        self.repetition = repetition
        self.billing = billing
        self.batch = batch

        self.training_stats = TrainingStats()
        self.validation_scores = ValidationScores()
        self.started = None
        self.stopped = None
        self.num_parameters = None

        self.hash = (
            "-".join(
                [
                    self.task_config.hash,
                    self.data_config.hash,
                    self.model_config.hash,
                    self.optimizer_config.hash,
                ]
            )
            + ":"
            + str(self.repetition)
        )

        run_id = hashlib.md5()
        run_id.update(self.task_config.id.encode())
        run_id.update(self.data_config.id.encode())
        run_id.update(self.model_config.id.encode())
        run_id.update(self.optimizer_config.id.encode())
        run_id.update(str(self.repetition).encode())
        self.id = run_id.hexdigest()

        self.validation_interval = validation_interval
        self.keep_best_validation = keep_best_validation
        if keep_best_validation is not None:
            tokens = keep_best_validation.split(":")
            self.best_score_name = tokens[1]
            self.best_score_relation = {"min": min, "max": max}[tokens[0]]
        else:
            self.best_score_name = None
        self.snapshot_interval = snapshot_interval

    def start(self):

        # set torch flags:
        # TODO: make these configurable?
        torch.backends.cudnn.enabled = True
        torch.backends.cudnn.benchmark = True

        store = MongoDbStore()
        store.sync_run(self)

        if self.stopped is not None:
            print(f"SKIP: Run {self} was already completed earlier.")
            return

        self.started = time.time()

        data = Data(self.data_config)
        model = self.model_config.type(data, self.model_config)
        task = Task(data, model, self.task_config)

        parameters = [
            {"params": model.parameters()},
            {"params": task.predictor.parameters()},
        ]

        for name, predictor, loss in task.aux_tasks:
            parameters.append(
                {"params": predictor.parameters()},
            )

        optimizer = self.optimizer_config.type(parameters, lr=self.optimizer_config.lr)

        outdir = os.path.join("runs", self.hash)
        print(f"Storing this run's data in {outdir}")
        os.makedirs(outdir, exist_ok=True)

        self.num_parameters = task.predictor.num_parameters()
        store.sync_run(self)
        pipeline, request = create_train_pipeline(
            task,
            data,
            task.predictor,
            optimizer,
            self.optimizer_config.batch_size,
            outdir=outdir,
            snapshot_every=self.snapshot_interval,
        )

        with gp.build(pipeline):

            for i in tqdm(range(self.optimizer_config.num_iterations), desc="train"):

                batch = pipeline.request_batch(request)

                train_time = batch.profiling_stats.get_timing_summary(
                    "Train", "process"
                ).times[-1]
                self.training_stats.add_training_iteration(i, batch.loss, train_time)

                if i % self.validation_interval == 0 and i > 0:
                    scores = validate(
                        data,
                        task.model,
                        task.predictor,
                        store_best_result=os.path.join(outdir, f"validate_{i}.zarr"),
                        best_score_name=self.best_score_name,
                        best_score_relation=self.best_score_relation,
                    )
                    self.validation_scores.add_validation_iteration(i, scores)
                    store.store_validation_scores(self)

                    if self.best_score_name is not None:

                        # get best sample-average score for each iteration over
                        # all post-processing parameters
                        best_iteration_scores = np.array(
                            [
                                self.best_score_relation(
                                    [
                                        v["scores"]["average"][self.best_score_name]
                                        for v in parameter_scores.values()
                                    ]
                                )
                                for parameter_scores in self.validation_scores.scores
                            ]
                        )

                        # replace nan
                        replace = -self.best_score_relation([-np.inf, np.inf])
                        isnan = np.isnan(best_iteration_scores)
                        best_iteration_scores[isnan] = replace

                        # get best score over all iterations
                        best = self.best_score_relation(best_iteration_scores)
                        if best == best_iteration_scores[-1]:
                            print(
                                f"Iteration {i} current best ({best}), "
                                "storing checkpoint..."
                            )
                            task.predictor.save(
                                os.path.join(
                                    outdir,
                                    f"validation_best_{self.best_score_name}.checkpoint",
                                ),
                                optimizer,
                            )

                if i % 100 == 0 and i > 0:
                    store.store_training_stats(self)

        store.store_training_stats(self)
        self.stopped = time.time()
        store.sync_run(self)

        # TODO:
        # testing

    def to_dict(self):

        return {
            "task_config": self.task_config.id,
            "model_config": self.model_config.id,
            "optimizer_config": self.optimizer_config.id,
            "repetition": self.repetition,
            "started": self.started,
            "stopped": self.stopped,
            "num_parameters": self.num_parameters,
            "id": self.id,
            "hash": self.hash,
        }

    def __repr__(self):
        return f"{self.hash}"


def enumerate_runs(
    task_configs,
    data_configs,
    model_configs,
    optimizer_configs,
    repetitions,
    validation_interval,
    snapshot_interval,
    keep_best_validation,
    billing,
    batch,
):

    runs = []
    for task_config in task_configs:
        for data_config in data_configs:
            for model_config in model_configs:
                for optimizer_config in optimizer_configs:
                    for repetition in range(repetitions):
                        runs.append(
                            Run(
                                task_config,
                                data_config,
                                model_config,
                                optimizer_config,
                                repetition,
                                validation_interval,
                                snapshot_interval,
                                keep_best_validation,
                                billing,
                                batch,
                            )
                        )
    return runs


def run_local(run):

    print(
        f"Running task {run.task_config} "
        f"with data {run.data_config}, "
        f"with model {run.model_config}, "
        f"using optimizer {run.optimizer_config}"
    )

    run.start()


def run_remote(run):
    if run.billing is not None:
        flags = [f"-P {run.billing}"]
    else:
        flags = None

    funlib.run.run(
        command=f"dacapo run-one "
        f"-t {run.task_config.config_file} "
        f"-d {run.data_config.config_file} "
        f"-m {run.model_config.config_file} "
        f"-o {run.optimizer_config.config_file} "
        f"-R {run.repetition} "
        f"-v {run.validation_interval} "
        f"-s {run.snapshot_interval} "
        f"-b {run.keep_best_validation} ",
        num_cpus=2,
        num_gpus=1,
        queue="gpu_any",
        execute=True,
        flags=flags,
        batch=run.batch,
        log_file=f"runs/{run.hash}/log.out",
        error_file=f"runs/{run.hash}/log.err",
    )


def run_all(runs, num_workers):

    print(f"Running {len(runs)} configs:")
    for run in runs[:10]:
        print(f"\t{run}")
    if len(runs) > 10:
        print(f"(and {len(runs) - 10} more...)")

    if num_workers > 1:

        from multiprocessing import Pool

        with Pool(num_workers) as pool:
            pool.map(run_remote, runs)

    else:

        for run in runs:
            run_local(run)
