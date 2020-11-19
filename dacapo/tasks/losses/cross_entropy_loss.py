import torch
from .loss import Loss

from dacapo.gp.binarize import Binarize


class CrossEntropyLoss(torch.nn.CrossEntropyLoss, Loss):
    def __init__(self, weight=None, ignore_label: int = -100):
        self.__ignore_label = ignore_label

        if weight is not None:
            weight = torch.tensor(weight)

        super(CrossEntropyLoss, self).__init__(weight, ignore_index=ignore_label)

    def add_mask(self, gt, mask):
        return Binarize(input_array=gt, output_array=mask, target=self.__ignore_label)
