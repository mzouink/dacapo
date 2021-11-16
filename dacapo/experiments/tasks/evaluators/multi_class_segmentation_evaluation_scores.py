from .evaluation_scores import EvaluationScores
import attr


@attr.s
class MultiClassSegmentationEvaluationScores(EvaluationScores):

    frizz_level: float = attr.ib()
