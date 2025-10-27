#!/bin/bash

# 后台运行
#执行远程的训练命令
#nohup bash ./lbg/train.sh > outputs/log-train.txt 2>&1 &

/root/miniconda3/bin/conda init bash
source /root/miniconda3/etc/profile.d/conda.sh

export HF_ENDPOINT=https://hf-mirror.com

conda activate unifolm-wma


# If you already downloaded the repo:
cd /workspace/data/unifolm-world-model-action/

mkdir -p outputs/

git pull

bash scripts/train.sh