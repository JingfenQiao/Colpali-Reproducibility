from typing import Dict, List

import torch
from mteb.evaluation.evaluators import RetrievalEvaluator


def get_torch_device() -> str:
    """
    Returns the device and dtype to be used for torch tensors.
    """
    if torch.cuda.is_available():
        device = "cuda:0"
    elif torch.backends.mps.is_available():  # for Apple Silicon
        device = "mps"
    else:
        device = "cpu"
    return device


class CustomRetrievalEvaluator:
    def __init__(self, is_multi_vector: bool = False):
        self.is_multi_vector = is_multi_vector
        self.mteb_evaluator = RetrievalEvaluator()
        self.device = get_torch_device()

    def evaluate(
        self,
        qs: List[torch.Tensor],
        ps: List[torch.Tensor],
    ):
        if self.is_multi_vector:
            scores = self.evaluate_colbert(qs, ps)
        else:
            scores = self.evaluate_biencoder(qs, ps)

        assert scores.shape[0] == len(qs)

        arg_score = scores.argmax(dim=1)
        # compare to arange
        accuracy = (arg_score == torch.arange(scores.shape[0], device=scores.device)).sum().item() / scores.shape[0]
        print(arg_score)
        print(f"Top 1 Accuracy (verif): {accuracy}")

        # cast to numpy
        # scores = scores.cpu().numpy()
        scores = scores.to(torch.float32).cpu().numpy()

        return scores

    def compute_metrics(
        self,
        relevant_docs: Dict[str, dict[str, int]],
        results: Dict[str, dict[str, float]],
        **kwargs,
    ) -> Dict[str, float]:
        """
        Compute the MTEB retrieval metrics.
        """
        ndcg, _map, recall, precision, naucs = self.mteb_evaluator.evaluate(
            relevant_docs,
            results,
            self.mteb_evaluator.k_values,
            ignore_identical_ids=kwargs.get("ignore_identical_ids", True),
        )

        mrr = self.mteb_evaluator.evaluate_custom(relevant_docs, results, self.mteb_evaluator.k_values, "mrr")

        scores = {
            **{f"ndcg_at_{k.split('@')[1]}": v for (k, v) in ndcg.items()},
            **{f"map_at_{k.split('@')[1]}": v for (k, v) in _map.items()},
            **{f"recall_at_{k.split('@')[1]}": v for (k, v) in recall.items()},
            **{f"precision_at_{k.split('@')[1]}": v for (k, v) in precision.items()},
            **{f"mrr_at_{k.split('@')[1]}": v for (k, v) in mrr[0].items()},
            **{f"naucs_at_{k.split('@')[1]}": v for (k, v) in naucs.items()},
        }

        return scores

    def evaluate_colbert(
        self,
        qs: List[torch.Tensor],
        ps: List[torch.Tensor],
        batch_size=128,
    ) -> torch.Tensor:
        """
        Compute the MaxSim score (ColBERT-like) for the given multi-vector query and passage embeddings.
        """

        scores = []

        for i in range(0, len(qs), batch_size):
            scores_batch = []
            qs_batch = torch.nn.utils.rnn.pad_sequence(qs[i : i + batch_size], batch_first=True, padding_value=0).to(
                self.device
            )
            for j in range(0, len(ps), batch_size):
                ps_batch = torch.nn.utils.rnn.pad_sequence(
                    ps[j : j + batch_size], batch_first=True, padding_value=0
                ).to(self.device)
                scores_batch.append(torch.einsum("bnd,csd->bcns", qs_batch, ps_batch).max(dim=3)[0].sum(dim=2))
            scores_batch = torch.cat(scores_batch, dim=1).cpu()
            scores.append(scores_batch)

        scores = torch.cat(scores, dim=0)

        return scores

    def evaluate_biencoder(
        self,
        qs: List[torch.Tensor],
        ps: List[torch.Tensor],
    ) -> torch.Tensor:
        """
        Compute the dot product score for the given single-vector query and passage embeddings.
        """

        qs_stacked = torch.stack(qs)
        ps_stacked = torch.stack(ps)

        scores = torch.einsum("bd,cd->bc", qs_stacked, ps_stacked)

        return scores
