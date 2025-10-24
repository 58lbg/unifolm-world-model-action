#!/bin/bash

conda create -n unifolm-wma python==3.10.18
conda activate unifolm-wma

conda install pinocchio=3.2.0 -c conda-forge -y
conda install ffmpeg=7.1.1 -c conda-forge

# If you already downloaded the repo:
cd /workspace/data/unifolm-world-model-action/
git pull
git submodule update --init --recursive

pip install -e .

cd external/dlimp
pip install -e .

cd /workspace/data/unifolm-world-model-action/
bash scripts/train.sh