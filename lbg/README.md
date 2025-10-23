python prepare_training_data.py \
    --source_dir ~/Desktop/lerobot \
    --target_dir ~/Desktop/lerobot/unifolm-test \
    --dataset_name "smolvla_test_0818" \
    --robot_name "unifolm world so100 test"


huggingface-cli download unitreerobotics/UnifoLM-WMA-0-Base --local-dir ../lbg/model/UnifoLM-WMA-0-Base