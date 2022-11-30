import os
import sys

if len(sys.argv) != 3:
    print("Parameters: <exp-name> <java-jsonl-data-dir>")
    exit()
EXP_NAME = sys.argv[1]
DATA_CODE_SEARCH_NET_JAVA_DIR = sys.argv[2]
DATA_CODE_SEARCH_NET_JAVA_DIR_TRAIN = os.path.join(DATA_CODE_SEARCH_NET_JAVA_DIR, "train/")
DATA_CODE_SEARCH_NET_JAVA_DIR_VALID =  os.path.join(DATA_CODE_SEARCH_NET_JAVA_DIR, "valid/")
DATA_CODE_SEARCH_NET_JAVA_DIR_TEST =  os.path.join(DATA_CODE_SEARCH_NET_JAVA_DIR, "test/")
TRACE_BERT_CODE_DIR = "TraceBERT-master"

print("EXP_NAME: " + EXP_NAME)
print("DATA_CODE_SEARCH_NET_JAVA_DIR: " + DATA_CODE_SEARCH_NET_JAVA_DIR)
print("TRACE_BERT_CODE_DIR: " + TRACE_BERT_CODE_DIR)
print()

import gzip
import json
#import logging
import multiprocessing
import pathlib
import torch

sys.path.append(TRACE_BERT_CODE_DIR)

class TrainArgs:
    def __init__(self):
        """The input data dir. Should contain the .json files for the task."""
        self.data_dir: str = "./data"
        """path of checkpoint and trained model, if none will do training from scratch"""
        self.model_path: str = None
        """Log every X updates steps"""
        self.logging_steps: int = 500
        """Whether not to use CUDA when available"""
        self.no_cuda: bool = False
        """number of instances used for evaluating the checkpoint performance"""
        self.valid_num: int = 100
        """obtain validation accuracy every given steps"""
        self.valid_step: int = 50
        """number of instances used for training"""
        self.train_num: int = None
        """overwrite the cached data"""
        self.overwrite: bool = False
        """Batch size per GPU/CPU for training."""
        self.per_gpu_train_batch_size: int = 8
        """Batch size per GPU/CPU for evaluation."""
        self.per_gpu_eval_batch_size: int = 8
        """local_rank for distributed training on gpus"""
        self.local_rank: int = -1
        """Whether to use 16-bit (mixed) precision (through NVIDIA apex) instead of 32-bit"""
        self.fp16: bool = False
        """random seed for initialization"""
        self.seed: int = 42
        """Number of updates steps to accumulate before performing a backward/update pass."""
        self.gradient_accumulation_steps: int = 1
        """Weight decay if we apply some."""
        self.weight_decay: float = 0.0
        """Epsilon for Adam optimizer."""
        self.adam_epsilon: float = 1e-8
        """Max gradient norm."""
        self.max_grad_norm: float = 1.0
        """Save checkpoint every X updates steps."""
        self.save_steps: int = 500
        """If > 0: set total number of training steps to perform. Override num_train_epochs."""
        self.max_steps: int = -1
        """The output directory where the model checkpoints and predictions will be written"""
        self.output_dir: str = None
        """The initial learning rate for Adam."""
        self.learning_rate: float = 5e-5
        """Total number of training epochs to perform."""
        self.num_train_epochs: float = 3.0
        """name of this execution"""
        self.exp_name: str = "exp" # no default in original code
        """The ration of hard negative examples in a batch during negative sample mining"""
        self.hard_ratio: float = 0.5
        """Linear warmup over warmup_steps."""
        self.warmup_steps: int = 0
        """Negative sampling strategy we apply for constructing dataset."""
        self.neg_sampling: str = "random"
        self.NEG_SAMPLING_POSSIBLE_VALUES = ['random', 'online', 'offline']
        """"""
        self.code_bert: str = "microsoft/codebert-base"
        self.CODE_BERT_POSSIBLE_VALUES = [
            'microsoft/codebert-base',
            'huggingface/CodeBERTa-small-v1',
            'codistai/codeBERT-small-v2'
        ]
        """
        For fp16: Apex AMP optimization level selected in ['O0', 'O1', 'O2', and 'O3'].
        See details at https://nvidia.github.io/apex/amp.html
        """
        self.fp16_opt_level: str = "O1"

class EvalArgs:
    def __init__(self):
        """The input data dir. Should contain the .json files for the task."""
        self.data_dir: str = "../data/code_search_net/python"
        """The model to evaluate"""
        self.model_path: str = None
        """Whether not to use CUDA when available"""
        self.no_cuda: bool = False
        """The number of true links used for evaluation. The retrival task is build around the true links"""
        self.test_num: int = 1000 # NO DEFAULT in original code
        """Batch size per GPU/CPU for evaluation."""
        self.per_gpu_eval_batch_size: int = 8
        """directory to store the results"""
        self.output_dir: str = "./evaluation/test"
        """overwrite the cached data"""
        self.overwrite: bool = False
        """the base bert"""
        self.code_bert: str = "microsoft/codebert-base"
        """id for this run of experiment"""
        self.exp_name: str = "exp"
        """The number of queries in each chunk of retrivial task"""
        self.chunk_query_num: int = -1
        # AN EXTRA LINE HERE modifying output_dir in original code
        #args.output_dir = os.path.join(args.output_dir, args.exp_name)

def get_raw_examples(data_dir, data_nl_key, data_pl_key, num_limit=None, nl_transform=lambda x: x, pl_transform=lambda x: x):
    jsonl_filenames = list(pathlib.Path(data_dir).glob("*.jsonl.gz"))
    if len(jsonl_filenames) > 0:
        gz = True
    else:
        jsonl_filenames = list(pathlib.Path(data_dir).glob("*.jsonl"))
        if len(jsonl_filenames) == 0:
            return []
        gz = False

    examples = []
    count = 0
    for filename in jsonl_filenames:
        lines = []
        if gz:
            with gzip.open(filename, 'r') as file:
                lines = file.readlines()
        else:
            with open(filename, 'r') as file:
                lines = file.readlines()
        for line in lines:
            if num_limit != None and count >= num_limit:
                return examples
            json_obj = json.loads(line)
            nl = nl_transform(json_obj[data_nl_key]) # summerizes by default
            pl = pl_transform(json_obj[data_pl_key])
            if nl != None and pl != None:
                examples.append({
                    "NL": nl,
                    "PL": pl
                })
                count += 1
    return examples

from common.data_structures import Examples
from common.models import TwinBert, TBertT, TBertI, TBertS, TBertI2

#logger = logging.getLogger(__name__)

def load_examples(data_dir, data_nl_key, data_pl_key, model: TwinBert,
                 overwrite=False, num_limit=None,
                 nl_transform=lambda x: x, pl_transform=lambda x: x,
                 cache_file_name="cached_classify.dat"):
    cache_dir = os.path.join(data_dir, "cache")
    if not os.path.isdir(cache_dir):
        os.mkdir(cache_dir)
    cached_file = os.path.join(cache_dir, cache_file_name)
    if os.path.exists(cached_file) and not overwrite:
        #logger.info("Loading examples from cached file {}".format(cached_file))
        examples = torch.load(cached_file)
    else:
        #logger.info("Creating examples from dataset file at {}".format(data_dir))
        raw_examples = get_raw_examples(data_dir, data_nl_key, data_pl_key, num_limit=num_limit, nl_transform=nl_transform, pl_transform=pl_transform)
        examples = Examples(raw_examples)
        if isinstance(model, TBertT) or isinstance(model, TBertI):
            examples.update_features(model, multiprocessing.cpu_count())
        #logger.info("Saving processed examples into cached file {}".format(cached_file))
        torch.save(examples, cached_file)
    return examples

# Modified version of single train

args = TrainArgs()
#args.data_dir = DATA_CODE_SEARCH_NET_JAVA_DIR
args.output_dir = "./output"
args.per_gpu_train_batch_size = 8
args.per_gpu_eval_batch_size = 8
args.logging_steps = 10
args.save_steps = 100000 # 10000
args.gradient_accumulation_steps = 16
args.num_train_epochs = 80 # 8
args.learning_rate = 4e-5
args.valid_num = 200
args.valid_step = 100000 # 10000
args.neg_sampling = "random"

# More
args.overwrite = True
args.exp_name = EXP_NAME

def nl_transform_tokens(tokens): # list to str
    result = ' '.join(tokens)
    result = result[:result.find("<p >")]
    if len(result.split()) < 10:
        return None
    return result

def pl_transform_tokens(tokens): # list to str
    return ' '.join([' '.join(token.split()) for token in tokens])

from code_search.twin.twin_train import init_train_env, train
#from code_search.single.single_train import train_single_iteration
from single_train_modified import train_single_iteration, init_train_single_iteration

init_train_single_iteration()

model = init_train_env(args, tbert_type='single')
valid_examples = load_examples(DATA_CODE_SEARCH_NET_JAVA_DIR_VALID, "docstring_tokens", "code_tokens", model=model, num_limit=args.valid_num,
                                overwrite=args.overwrite, nl_transform=nl_transform_tokens, pl_transform=pl_transform_tokens)
train_examples = load_examples(DATA_CODE_SEARCH_NET_JAVA_DIR_TRAIN, "docstring_tokens", "code_tokens", model=model, num_limit=args.train_num,
                                overwrite=args.overwrite, nl_transform=nl_transform_tokens, pl_transform=pl_transform_tokens)
train(args, train_examples, valid_examples, model, train_single_iteration)
#logger.info("Training finished")