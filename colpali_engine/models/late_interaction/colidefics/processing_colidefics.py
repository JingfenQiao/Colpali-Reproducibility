from __future__ import annotations

from typing import List, Optional

from PIL import Image
from transformers import BatchEncoding, Idefics2Processor

from colpali_engine.utils.processing_utils import BaseVisualRetrieverProcessor


class ColIdefics2Processor(BaseVisualRetrieverProcessor, Idefics2Processor):
    def __init__(self, image_processor):
        super().__init__(image_processor)

    def process_images(
        self,
        images: List[Image.Image],
    ) -> BatchEncoding:
        """
        Process images for ColIdefics2, with an efficient tweak around the Idefics2 processor.
        """
        texts_doc = []
        images = [image.convert("RGB") for image in images]

        for _ in images:
            messages_doc = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe the image."},
                        {"type": "image"},
                    ],
                },
            ]

            text_doc = self.apply_chat_template(messages_doc, add_generation_prompt=False)
            texts_doc.append(text_doc.strip())

        batch_doc = self(
            text=texts_doc,
            images=images,
            return_tensors="pt",
            padding="longest",
        )
        return batch_doc

    def process_queries(
        self,
        queries: List[str],
        max_length: int = 50,
        suffix: Optional[str] = None,
    ) -> BatchEncoding:
        """
        Process queries for ColIdefics2, with an efficient tweak around the Idefics2 processor.
        """
        suffix = suffix or "<end_of_utterance>" * 5
        texts_query = []
        for query in queries:
            messages_query = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Question: {query}" + suffix,
                        },
                    ],
                },
            ]
            text_query = self.apply_chat_template(messages_query, add_generation_prompt=False).strip()
            texts_query.append(text_query)

        batch_query = self(
            text=texts_query,
            return_tensors="pt",
            padding="longest",
            max_length=max_length,
        )
        return batch_query
