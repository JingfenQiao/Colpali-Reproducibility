import torch
from transformers import Trainer


class ContrastiveTrainer(Trainer):
    def __init__(self, loss_func, is_vision_model, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.loss_func = loss_func
        self.is_vision_model = is_vision_model

    def compute_loss(self, model, inputs, return_outputs=False):
        query_outputs = model(input_ids=inputs["query_input_ids"], attention_mask=inputs["query_attention_mask"])

        # hacky, to make sure the scatter in DDP is done correctly
        if "image_grid_thw" in inputs:
            # compute pixel_values offsets
            offsets = torch.cumsum(inputs["image_grid_thw"][:, 1] * inputs["image_grid_thw"][:, 2], 0)
            print(offsets)
            # separate pixel_values for each image
            pixel_values = torch.split(inputs["pixel_values"], offsets.tolist())
            # pad pixel_values to the same length to be able to make it into a tensor
            max_length = max([len(pv) for pv in pixel_values])
            pixel_values = [torch.cat([pv, torch.zeros(max_length - len(pv), dtype=pv.dtype, device=pv.device)]) for pv in pixel_values]
            inputs["pixel_values"] = torch.stack(pixel_values)

            print(inputs["pixel_values"].shape)


        doc_outputs = model(**{k[4:]: v for k, v in inputs.items() if k.startswith("doc")})
        if "neg_doc_input_ids" in inputs:
            neg_doc_outputs = model(**{k[8:]: v for k, v in inputs.items() if k.startswith("neg_doc")})
            loss = self.loss_func(query_outputs, doc_outputs, neg_doc_outputs)
            return (loss, (query_outputs, doc_outputs, neg_doc_outputs)) if return_outputs else loss

        loss = self.loss_func(query_outputs, doc_outputs)
        return (loss, (query_outputs, doc_outputs)) if return_outputs else loss

    def prediction_step(self, model, inputs, prediction_loss_only, ignore_keys=True):
        """This function is used to generate predictions and return the loss for the given inputs."""
        if not prediction_loss_only:
            raise ValueError("prediction_step is only called with prediction_loss_only=True")

        with torch.no_grad():
            doc_outputs = model(**{k[4:]: v for k, v in inputs.items() if k.startswith("doc")})
            query_outputs = model(input_ids=inputs["query_input_ids"], attention_mask=inputs["query_attention_mask"])
            if "neg_doc_input_ids" in inputs:
                neg_doc_outputs = model(**{k[8:]: v for k, v in inputs.items() if k.startswith("neg_doc")})
                loss = self.loss_func(query_outputs, doc_outputs, neg_doc_outputs)
                return loss, None, None

            loss = self.loss_func(query_outputs, doc_outputs)
            return loss, None, None
