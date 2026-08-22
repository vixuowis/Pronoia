#!/bin/bash
# Pronoia-RLVR smoke 测试：100 条样本 × 1 epoch，验证数据/模板/LoRA/GPU 全链路
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
    --dataset_dir /root/LLaMA-Factory/data/rlvr \
    --template qwen3 \
    --cutoff_len 3072 \
    --max_samples 100 \
    --overwrite_cache \
    --preprocessing_num_workers 8 \
    --dataloader_num_workers 2 \
    --output_dir /root/autodl-tmp/rlvr/smoke_sft \
    --logging_steps 2 \
    --save_steps 1000 \
    --plot_loss \
    --overwrite_output_dir \
    --save_only_model false \
    --report_to none \
    --per_device_train_batch_size 2 \
    --gradient_accumulation_steps 4 \
    --learning_rate 1e-4 \
    --num_train_epochs 1.0 \
    --lr_scheduler_type cosine \
    --warmup_ratio 0.1 \
    --bf16 \
    --ddp_timeout 180000000 2>&1

echo "SMOKE_EXIT_CODE=$?"
