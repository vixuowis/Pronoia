import os
import time
import torch
import torch.distributed as dist
from vllm.distributed import StatelessProcessGroup

rank = int(os.environ["RANK"])
port = int(os.environ.get("PG_PORT", 29557))
host = "0.0.0.0" if rank == 0 else "127.0.0.1"
pg = StatelessProcessGroup.create(host=host, port=port, rank=rank, world_size=2)
print(f"[{rank}] pg created", flush=True)

N = 256 * 1024 * 1024  # 256M elements bf16 = 512MB
if rank == 1:
    t = torch.full((N,), 3.0, dtype=torch.bfloat16, device="cuda")
else:
    t = torch.zeros((N,), dtype=torch.bfloat16, device="cuda")

if rank == 0:
    dist.broadcast(t, src=1, group=pg)
    print(f"[{rank}] broadcast done, checksum={t.float().sum().item() / N:.3f}", flush=True)
else:
    t0 = time.time()
    dist.broadcast(t, src=1, group=pg)
    torch.cuda.synchronize()
    print(f"[{rank}] broadcast 512MB took {time.time()-t0:.2f}s", flush=True)

pg.barrier()
print(f"[{rank}] barrier ok", flush=True)
