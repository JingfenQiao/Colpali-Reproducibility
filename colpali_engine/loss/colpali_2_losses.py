from dataclasses import dataclass
from typing import Optional, Tuple, Union

import torch
import torch.nn as nn
import torch.nn.functional as F  # noqa: N812

from colpali_engine.loss.base_late_interaction_loss import BaseColbertLoss
from colpali_engine.loss.matryoshka_loss import MatryoshkaCELoss
from colpali_engine.models.paligemma.colpali_2.modeling_colpali_2 import ColPali2ModelOutput


@dataclass(kw_only=True)
class ColPali2LossOutputs:
    single_vector_loss: torch.Tensor
    multi_vector_loss: torch.Tensor
    distillation_loss: Optional[torch.Tensor] = None
    total_loss: torch.Tensor


class ColPali2Loss(BaseColbertLoss):
    """
    Loss function for ColPali2.

    The loss function is a combination of two losses:
    1. Single-vector loss: Cross-entropy (with optional Matryoshka) loss between the query and document
        single-vector embeddings.
    2. Multi-vector loss: Margin loss between the query and document multi-vector embeddings.
    """

    def __init__(
        self,
        alpha: float = 0.5,
        use_matryoshka_loss: bool = True,
        use_distillation_loss: bool = True,
        beta: float = 0.5,
        temperature: float = 2.0,
    ):
        super().__init__()
        self.alpha = alpha
        self.use_matryoshka_loss = use_matryoshka_loss
        self.use_distillation_loss = use_distillation_loss
        self.beta = beta
        self.temperature = temperature
        self.single_vector_loss_fn = MatryoshkaCELoss() if self.use_matryoshka_loss else F.cross_entropy

    def single_vector_loss(
        self,
        query_embeddings: torch.Tensor,
        doc_embeddings: torch.Tensor,
        return_scores: bool = False,
    ) -> Union[torch.Tensor, Tuple[torch.Tensor, torch.Tensor]]:
        """
        Compute the loss function for the single-vector head.

        Args:
        - query_embeddings: (batch_size, dim)
        - doc_embeddings: (batch_size, dim)

        Returns:
        - torch.Tensor: The loss value (1,)
        - Optional[torch.Tensor]: The scores matrix (batch_size, batch_size) if `return_scores` is True
        """

        if query_embeddings.shape[0] != doc_embeddings.shape[0]:
            raise ValueError("Batch size mismatch between query and document embeddings.")

        scores = torch.einsum("bd,cd->bc", query_embeddings, doc_embeddings)  # (batch_size, batch_size)

        loss = self.single_vector_loss_fn(scores, torch.arange(scores.shape[0], device=scores.device))  # (1,)

        if return_scores:
            return loss, scores
        else:
            return loss

    def multi_vector_loss(
        self,
        query_embeddings: torch.Tensor,
        doc_embeddings: torch.Tensor,
        return_scores: bool = False,
    ) -> Union[torch.Tensor, Tuple[torch.Tensor, torch.Tensor]]:
        """
        Compute the loss function for the multi-vector head.

        Args:
        - query_embeddings: (batch_size, num_query_tokens, dim)
        - doc_embeddings: (batch_size, num_doc_tokens, dim)

        Returns:
        - torch.Tensor: The loss value (1,)
        - Optional[torch.Tensor]: The scores matrix (batch_size, batch_size) if `return_scores` is True
        """

        if query_embeddings.shape[0] != doc_embeddings.shape[0]:
            raise ValueError("Batch size mismatch between query and document embeddings.")

        # Compute the ColBERT scores
        scores = self.compute_colbert_scores(query_embeddings, doc_embeddings)  # (batch_size, batch_size)

        # Positive scores are the diagonal of the scores matrix.
        pos_scores = scores.diagonal()  # (batch_size,)

        # Negative score for a given query is the maximum of the scores against all all other pages.
        # NOTE: We subtract a large value from the diagonal to exclude it from the maximum operation.
        neg_scores = scores - torch.eye(scores.shape[0], device=scores.device) * 1e6  # (batch_size, batch_size)
        neg_scores = neg_scores.max(dim=1)[0]  # (batch_size,)

        # Compute the margin loss
        loss = F.softplus(neg_scores - pos_scores).mean()  # (1,)

        if return_scores:
            return loss, scores
        else:
            return loss

    def distillation_loss(
        self,
        teacher_scores: torch.Tensor,
        student_scores: torch.Tensor,
    ) -> torch.Tensor:
        """
        Compute the distillation loss between the multi-vector head (teacher) and
        the single-vector head (student).

        Args:
        - teacher_scores: (batch_size, batch_size)
        - student_scores: (batch_size, batch_size)

        Returns:
        - torch.Tensor: The loss value (1,)
        - Optional[torch.Tensor]: The scores matrix (batch_size, batch_size) if `return_scores` is True
        """

        if teacher_scores.shape != student_scores.shape:
            raise ValueError("Teacher and student scores should have the same shape.")

        kl_div_loss = nn.KLDivLoss(log_target=True)

        # NOTE: Both the teacher and student scores should be turned into log-probabilities before
        # computing the KL-divergence.

        # Convert the scores to probabilities
        teacher_scores = torch.softmax(teacher_scores, dim=1)  # (batch_size, batch_size)
        student_scores = torch.softmax(student_scores, dim=1)  # (batch_size, batch_size)

        # Get log-probabilities
        teacher_logits = torch.logit(teacher_scores, eps=1e-6)  # (batch_size, batch_size)
        student_logits = torch.logit(student_scores, eps=1e-6)  # (batch_size, batch_size)

        # NOTE:
        # - KLDivLoss argument order is the opposite of the KL(·||·) mathematical function.
        # - KLDivLoss expects log-probabilities for `input` to avoid underflow issues.

        loss_kd = self.temperature**2 * kl_div_loss(
            input=student_logits / self.temperature,
            target=teacher_logits / self.temperature,
        )  # (1,)

        return loss_kd

    def forward(
        self,
        query_embeddings: ColPali2ModelOutput,
        doc_embeddings: ColPali2ModelOutput,
    ) -> ColPali2LossOutputs:
        """
        Compute the total loss for the ColPali2 model.

        Args:
        - query_embeddings (ColPali2ModelOutput), all tensors with shape (batch_size, num_tokens, dim)
        - doc_embeddings (ColPali2ModelOutput), all tensors with shape (batch_size, num_tokens, dim)

        Returns:
        - ColPali2LossOutputs
        """

        single_vector_loss, single_vector_scores = self.single_vector_loss(
            query_embeddings.single_vec_emb, doc_embeddings.single_vec_emb, return_scores=True
        )
        multi_vector_loss, multi_vector_scores = self.multi_vector_loss(
            query_embeddings.multi_vec_emb, doc_embeddings.multi_vec_emb, return_scores=True
        )

        total_loss = self.alpha * single_vector_loss + (1 - self.alpha) * multi_vector_loss

        distillation_loss = None
        if self.use_distillation_loss:
            distillation_loss = self.distillation_loss(single_vector_scores, multi_vector_scores)
            total_loss += self.beta * distillation_loss

        return ColPali2LossOutputs(
            single_vector_loss=single_vector_loss,
            multi_vector_loss=multi_vector_loss,
            distillation_loss=distillation_loss,
            total_loss=total_loss,
        )
