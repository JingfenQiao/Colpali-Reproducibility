from typing import ClassVar

import torch
from torch import nn
from transformers.models.qwen2_vl import Qwen2VLConfig, Qwen2VLModel, Qwen2VLPreTrainedModel


class ColQwen2(Qwen2VLPreTrainedModel):
    """
    ColQwen2 model implementation from the "ColPali: Efficient Document Retrieval with Vision Language Models" paper.
    """

    main_input_name: ClassVar[str] = "doc_input_ids"  # transformers-related

    def __init__(self, config: Qwen2VLConfig):
        super().__init__(config=config)

        self.model = Qwen2VLModel(config=config)
        # TODO:  verify weight tying
        self.dim = 128
        self.custom_text_proj = nn.Linear(self.model.config.hidden_size, self.dim)

        self.post_init()

    def forward(self, *args, **kwargs) -> torch.Tensor:
        # Delete output_hidden_states from kwargs
        kwargs.pop("output_hidden_states", None)

        outputs = self.model(*args, output_hidden_states=True, **kwargs)  # (batch_size, sequence_length, hidden_size)
        last_hidden_states = outputs.hidden_states[-1]  # (batch_size, sequence_length, hidden_size)
        proj = self.custom_text_proj(last_hidden_states)  # (batch_size, sequence_length, dim)

        # L2 normalization
        proj = proj / proj.norm(dim=-1, keepdim=True)  # (batch_size, sequence_length, dim)

        proj = proj * kwargs["attention_mask"].unsqueeze(-1)  # (batch_size, sequence_length, dim)

        return proj
