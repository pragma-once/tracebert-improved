python twin_train.py \
--data_dir ../data/code_search_net/python \
--output_dir ./output \
--per_gpu_train_batch_size 4 \
--per_gpu_eval_batch_size 4 \
--logging_steps 10 \
--save_steps 2000 \
--gradient_accumulation_steps 16 \
--num_train_epochs 8 \
--learning_rate 4e-5 \
--valid_num 200 \
--valid_step 100 \
--neg_sampling online