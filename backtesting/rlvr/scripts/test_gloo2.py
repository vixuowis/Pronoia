import os
import time
import torch
from torch.distributed import TCPStore, ProcessGroup, ProcessGroupGloo

rank = int(os.environ["RANK"])
port = int(os.environ.get("PG_PORT", 29558))
store = TCPStore(host_name="127.0.0.1", port=port, world_size=2, is_master=(rank == 0),
                 use_libuv=False)
pg = ProcessGroup(store, rank, 2)
gloo = ProcessGroupGloo(store, rank, 2)
pg._set_default_backend(ProcessGroup.BackendType.GLOO)
pg._register_backend(torch.device("cpu"), ProcessGroup.BackendType.GLOO, gloo)
pg._register_backend(torch.device("cuda"), ProcessGroup.BackendType.GLOO, gloo)
print(f"[{rank}] gloo pg ready", flush=True)

N = 128 * 1024 * 1024  # 128M bf16 = 256MB
t = torch.full((N,), float(rank + 3), dtype=torch.bfloat16, device="cuda")

# rank1 (src) -> rank0
if rank == 1:
    torch.cuda.synchronize(); t0 = time.time()
    work = gloo.broadcast(t, 1)
    work.wait()
    torch.cuda.synchronize()
    print(f"[{rank}] CUDA broadcast 256MB took {time.time()-t0:.2f}s", flush=True)
else:
    work = gloo.broadcast(t, 1)
    work.wait()
    torch.cuda.synchronize()
    print(f"[{rank}] received checksum={t.float().sum().item()/N:.3f}", flush=True)

# barrier
w = gloo.barrier(); w.wait() if w is not None else None
print(f"[{rank}] barrier ok", flush=True)
