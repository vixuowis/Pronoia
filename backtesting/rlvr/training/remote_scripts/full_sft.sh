#!/bin/bash
# Pronoia-RLVR 全量 SFT：4800 train / 200 val × 3 epochs，LoRA rank8
export PATH=/root/miniconda3/bin:$PATH
cd /root/LLaMA-Factory/

llamafactory-cli train \
    --model_name_or_path /root/Qwen3-8B \
    --trust_remote_code \
    --stage sft \
    --do_train \
    --finetuning_type lora \
    --lora_rank 8 \
    --lora_alpha 16 \
    --lora_target all \
    --dataset rlvr_rft_train \
    --eval_dataset rlvr_rft_val \
    --dataset_dir /root/LLaMA-Factory/data/rlvr \
    --template qwen3 \
    --cutoff_len 3072 \
    --overwrite_cache \
    --preprocessing_num_workers 8 \
    --dataloader_num_workers 2 \
    --output_dir /root/autodl-tmp/rlvr/full_sft_v1 \
    --logging_steps 10 \
    --save_steps 150 \
    --save_total_limit 3 \
    --plot_loss \
    --overwrite_output_dir \
    --save_only_model false \
    --report_to none \
    --per_device_train_batch_size 4 \
    --gradient_accumulation_steps 4 \
    --per_device_eval_batch_size 4 \
    --eval_strategy steps \
    --eval_steps 150 \
    --learning_rate 1e-4 \
    --num_train_epochs 3.0 \
    --lr_scheduler_type cosine \
    --warmup_ratio 0.05 \
    --bf16 \
    --ddp_timeout 180000000 2>&1

echo "FULL_EXIT_CODE=$?"
