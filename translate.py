from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer
from tqdm import tqdm
from typing import TextIO, List
import argparse
import torch
from dataset import get_dataloader, count_lines
import os


def main(
    sentences_path,
    output_path,
    source_lang,
    target_lang,
    batch_size,
    model_name: str = "facebook/m2m100_1.2B",
    tensorrt: bool = False,
    precision: int = 32,
    max_length: int = 128,
):

    if not os.path.exists(os.path.dirname(output_path)):
        os.makedirs(os.path.dirname(output_path))

    print("Loading tokenizer...")
    tokenizer = M2M100Tokenizer.from_pretrained(model_name)
    print("Loading model...")
    model = M2M100ForConditionalGeneration.from_pretrained(model_name)
    print(f"Model loaded.\n")

    tokenizer.src_lang = source_lang
    lang_code_to_idx = tokenizer.lang_code_to_id[target_lang]

    model.eval()

    total_lines: int = count_lines(sentences_path)
    print(f"We will translate {total_lines} lines.")
    data_loader = get_dataloader(
        filename=sentences_path,
        tokenizer=tokenizer,
        batch_size=batch_size,
        max_length=128,
    )

    if precision == 16:
        dtype = torch.float16
    elif precision == 32:
        dtype = torch.float32
    elif precision == 64:
        dtype = torch.float64
    else:
        raise ValueError("Precision must be 16, 32 or 64.")

    if tensorrt:
        import torch_tensorrt

        traced_model = torch.jit.trace(
            model, [torch.randn((batch_size, max_length)).to("cuda")]
        )
        model = torch_tensorrt.compile(
            traced_model,
            inputs=[torch_tensorrt.Input((batch_size, max_length), dtype=dtype)],
            enabled_precisions={dtype},
        )
    else:
        if torch.cuda.is_available():
            model.to("cuda", dtype=dtype)
        else:
            model.to("cpu", dtype=dtype)
            print("CUDA not available. Using CPU. This will be slow.")

    with tqdm(total=total_lines, desc="Dataset translation") as pbar, open(
        output_path, "w+", encoding="utf-8"
    ) as output_file:
        with torch.no_grad():
            for batch in data_loader:
                generated_tokens = model.generate(
                    **batch, forced_bos_token_id=lang_code_to_idx
                )
                tgt_text = tokenizer.batch_decode(
                    generated_tokens.cpu(), skip_special_tokens=True
                )

                print("\n".join(tgt_text), file=output_file)

                pbar.update(len(tgt_text))

    print(f"Translation done.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the translation experiments")
    parser.add_argument(
        "--sentences_path",
        type=str,
        required=True,
        help="Path to a txt file containing the sentences to translate. One sentence per line.",
    )

    parser.add_argument(
        "--output_path",
        type=str,
        required=True,
        help="Path to a txt file where the translated sentences will be written.",
    )

    parser.add_argument(
        "--source_lang",
        type=str,
        required=True,
        help="Source language id. See: https://huggingface.co/facebook/m2m100_1.2B",
    )

    parser.add_argument(
        "--target_lang",
        type=str,
        required=True,
        help="Target language id. See: https://huggingface.co/facebook/m2m100_1.2B",
    )

    parser.add_argument(
        "--batch_size",
        type=int,
        default=8,
        help="Batch size",
    )

    parser.add_argument(
        "--model_name",
        type=str,
        default="facebook/m2m100_1.2B",
        help="Path to the model to use. See: https://huggingface.co/models",
    )

    parser.add_argument(
        "--precision",
        type=int,
        default=32,
        choices=[16, 32, 64],
        help="Precision of the model. 16, 32 or 64.",
    )

    parser.add_argument(
        "--tensorrt",
        action="store_true",
        help="Use TensorRT to compile the model.",
    )

    args = parser.parse_args()

    main(
        sentences_path=args.sentences_path,
        output_path=args.output_path,
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        batch_size=args.batch_size,
        model_name=args.model_name,
        precision=args.precision,
        tensorrt=args.tensorrt,
    )