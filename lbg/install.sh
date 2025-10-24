#!/bin/bash

# 后台运行
#执行远程的训练命令
#nohup bash ./lbg/install.sh > outputs/log-all.txt 2>&1 &

/root/miniconda3/bin/conda init bash
source /root/miniconda3/etc/profile.d/conda.sh

conda create -n unifolm-wma python==3.10.18 -y
conda activate unifolm-wma

pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

conda install pinocchio=3.2.0 -c conda-forge -y
conda install ffmpeg=7.1.1 -c conda-forge -y

# If you already downloaded the repo:
cd /workspace/data/unifolm-world-model-action/

mkdir -p outputs/

git pull
git submodule update --init --recursive

pip install -e .

cd external/dlimp
pip install -e .

cd /workspace/data/unifolm-world-model-action/
bash scripts/train.sh