import torch
import pytorch_lightning as pl
from typing import Optional, List, Union

from tango.common.dataset_dict import DatasetDict
from tango.common.lazy import Lazy
from tango.common.registrable import Registrable
from tango.format import Format
from tango.step import Step

from tango.integrations.torch.data import DataLoader
from tango.integrations.torch.format import TorchFormat

from .model import LightningModule
from .loggers import LightningLogger
from .callbacks import LightningCallback
from .profilers import LightningProfiler
from .accelerators import LightningAccelerator


class LightningTrainer(pl.Trainer, Registrable):  # type: ignore
    """
    This is simply a :class:`~tango.common.Registrable` version of
    the PyTorch Lightning :class:`~pytorch_lightning.trainer.trainer.Trainer`.
    """

    def _to_params(self):
        return {}


LightningTrainer.register("default")(LightningTrainer)


@Step.register("pytorch_lightning::train")
class LightningTrainStep(Step):
    """
    A step for training a model using PyTorch Lightning.

    .. tip::

        Registered as a :class:`~tango.step.Step` under the name "pytorch_lightning::train".
    """

    DETERMINISTIC: bool = True
    CACHEABLE = True
    FORMAT: Format = TorchFormat()

    def run(  # type: ignore[override]
        self,
        trainer: Lazy[LightningTrainer],
        model: LightningModule,
        dataset_dict: DatasetDict,
        train_dataloader: Lazy[DataLoader],
        train_split: str = "train",
        *,
        validation_dataloader: Lazy[DataLoader] = None,
        validation_split: str = "validation",
        loggers: Optional[List[Lazy[LightningLogger]]] = None,
        callbacks: Optional[List[Lazy[LightningCallback]]] = None,
        profiler: Optional[Union[str, Lazy[LightningProfiler]]] = None,
        accelerator: Optional[Union[str, Lazy[LightningAccelerator]]] = None,
    ) -> torch.nn.Module:

        """
        Run a basic training loop to train the ``model``.

        Parameters
        ----------

        trainer : :class:`LightningTrainer`
            The lightning trainer object.
        model : :class:`LightningModule`
            The lightning module to train.
        dataset_dict : :class:`~tango.common.dataset_dict.DatasetDict`
            The train and optional validation data.
        train_dataloader : :class:`DataLoader`
            The data loader that generates training batches. The batches should be :class:`dict`
            objects.
        train_split : :class:`str`, optional
            The name of the data split used for training in the ``dataset_dict``.
            Default is "train".
        validation_split : :class:`str`, optional
            Optional name of the validation split in the ``dataset_dict``. Default is ``None``,
            which means no validation.
        validation_dataloader : :class:`DataLoader`, optional
            An optional data loader for generating validation batches. The batches should be
            :class:`dict` objects. If not specified, but ``validation_split`` is given,
            the validation ``DataLoader`` will be constructed from the same parameters
            as the train ``DataLoader``.
        loggers: List[:class:`LightningLogger`]
            A list of :class:`LightningLogger`.
        callbacks: List[:class:`LightningCallback`]
            A list of :class:`LightningCallback`.
        profiler: Union[:class:`LightningProfiler`, :class:`str`], optional
            :class:`LightningProfiler` object.
        accelerator: Union[:class:`LightningAccelerator`, :class:`str`], optional
            :class:`LightningAccelerator` object.

        Returns
        -------
        :class:`LightningModule`
            The trained model on CPU with the weights from the best checkpoint loaded.

        """
        loggers: List[LightningLogger] = [
            logger.construct(save_dir=self.work_dir) for logger in (loggers or [])
        ]

        callbacks: List[LightningCallback] = [
            callback.construct() for callback in (callbacks or [])
        ]

        profiler: Optional[Union[str, LightningProfiler]] = (
            profiler.construct(dirpath=self.work_dir) if isinstance(profiler, Lazy) else profiler
        )

        accelerator: Optional[Union[str, LightningAccelerator]] = (
            accelerator.construct() if isinstance(accelerator, Lazy) else accelerator
        )

        trainer: LightningTrainer = trainer.construct(
            logger=loggers, callbacks=callbacks, profiler=profiler, accelerator=accelerator
        )

        checkpoint_callback: pl.callbacks.model_checkpoint.ModelCheckpoint

        for callback in trainer.callbacks:
            if isinstance(callback, pl.callbacks.model_checkpoint.ModelCheckpoint):
                callback.dirpath = self.work_dir
                checkpoint_callback = callback

        # Construct data loaders.
        validation_dataloader_: Optional[DataLoader] = None
        if validation_split is not None:
            if validation_dataloader is not None:
                validation_dataloader_ = validation_dataloader.construct(
                    dataset=dataset_dict[validation_split]
                )
            else:
                validation_dataloader_ = train_dataloader.construct(
                    dataset=dataset_dict[validation_split]
                )
        validation_dataloader: Optional[DataLoader] = validation_dataloader_

        try:
            train_dataset = dataset_dict[train_split]
        except KeyError:
            raise KeyError(f"'{train_split}', available keys are {list(dataset_dict.keys())}")

        train_dataloader: DataLoader = train_dataloader.construct(dataset=train_dataset)

        trainer.fit(model, train_dataloader, validation_dataloader)

        best_model = torch.load(checkpoint_callback.best_model_path)

        return best_model