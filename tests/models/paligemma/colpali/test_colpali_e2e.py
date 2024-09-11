from typing import cast

import pytest
import torch
from PIL import Image

from colpali_engine.models import ColPali, ColPaliProcessor
from colpali_engine.utils.torch_utils import get_torch_device


@pytest.mark.slow
def test_e2e_colpali():
    model = cast(
        ColPali,
        ColPali.from_pretrained(
            "vidore/colpali-v1.2",
            torch_dtype=torch.bfloat16,
            device_map=get_torch_device("auto"),
        ),
    )

    try:
        processor = cast(ColPaliProcessor, ColPaliProcessor.from_pretrained("google/paligemma-3b-mix-448"))

        # Your inputs
        images = [
            Image.new("RGB", (480, 480), color="white"),
            Image.new("RGB", (250, 250), color="black"),
        ]
        queries = [
            "Is attention really all you need?",
            "Are Benjamin, Antoine, Merve, and Jo best friends?",
        ]

        # Process the inputs
        batch_images = processor.process_images(images).to(model.device)
        batch_queries = processor.process_queries(queries).to(model.device)

        # Forward pass
        with torch.no_grad():
            image_embeddings = model(**batch_images)
            querry_embeddings = model(**batch_queries)

        scores = processor.score_multi_vector(querry_embeddings, image_embeddings)
        assert isinstance(scores, torch.Tensor)

    except Exception as e:
        pytest.fail(f"Code raised an exception: {e}")
