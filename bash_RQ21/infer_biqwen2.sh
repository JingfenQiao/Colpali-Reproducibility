#!/bin/sh
#SBATCH -p gpu
#SBATCH --job-name=colqwen
#SBATCH --mem=30G
#SBATCH --time=80:00:00
#SBATCH --output=/ivi/ilps/personal/jqiao/colpali/log4/infer_biqwen2-v1.3-PairwiseCELoss.output
#SBATCH --error=/ivi/ilps/personal/jqiao/colpali/log4/infer_biqwen2-v1.3-PairwiseCELoss.output
#SBATCH --gres=gpu:nvidia_rtx_a6000:1   # Request one GPU per task



vidore-benchmark evaluate-retriever \
    --model-class biqwen2 \
    --model-name biqwen2-PairwiseCELoss \
    --collection-name "vidore/vidore-benchmark-667173f98e70a1c0fa4db00d" \
    --split test