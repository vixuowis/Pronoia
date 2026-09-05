import os
import torch
from vllm.distributed import StatelessProcessGroup
from vllm.distributed.device_communicators.pynccl import PyNcclCommunicator

rank = int(os.environ["RANK"])
port = int(os.environ.get("PG_PORT", 29555))
host = "0.0.0.0" if rank == 0 else "127.0.0.1"
pg = StatelessProcessGroup.create(host=host, port=port, rank=rank, world_size=2)
print(f"[{rank}] pg created", flush=True)
comm = PyNcclCommunicator(pg, device=0)
print(f"[{rank}] NCCL comm OK", flush=True)
if rank == 1:
    t = torch.tensor([42.0], dtype=torch.float32, device="cuda")
    comm.broadcast(t, src=0)
    print(f"[{rank}] broadcast received: {t.item()}", flush=True)
else:
    t = torch.tensor([7.0], dtype=torch.float32, device="cuda")
    comm.broadcast(t, src=0)
    print(f"[{rank}] broadcast done", flush=True)
