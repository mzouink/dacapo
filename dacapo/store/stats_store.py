from abc import ABC, abstractmethod


class StatsStore(ABC):
    """Base class for statistics stores.
    """

    @abstractmethod
    def store_training_stats(self, run):
        """Store training stats of a given run."""
        pass

    @abstractmethod
    def retrieve_training_stats(self, run):
        """Retrieve the training stats for a given run."""
        pass

    @abstractmethod
    def store_validation_scores(self, run):
        """Store the validation scores of a given run."""
        pass

    @abstractmethod
    def retrieve_validation_scores(self, run):
        """Retrieve the validation scores for a given run."""
        pass
