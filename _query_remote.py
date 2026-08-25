"""一次性脚本：经 HTTP 代理 CONNECT 隧道连远端 GPU 主机，查询实时状态。"""
import base64
import socket
import paramiko

HOST = "connect.westd.seetacloud.com"
PORT = 12109
USER = "root"
PASS = "En6mms06iDbK"

PROXY_HOST = "127.0.0.1"
PROXY_PORT = 18080


def tunnel():
    """通过沙箱 HTTP 代理建立到远端 SSH 端口的 CONNECT 隧道。"""
    s = socket.create_connection((PROXY_HOST, PROXY_PORT), timeout=20)
    # 下面是 Agent 直连远端前先走的代理 CONNECT
    connect_req = f"CONNECT {HOST}:{PORT} HTTP/1.1\r\nHost: {HOST}:{PORT}\r\n" \
                  f"Proxy-Connection: Keep-Alive\r\n\r\n"
    s.sendall(connect_req.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = s.recv(4096)
        if not chunk:
            break
        resp += chunk
    if b" 200 " not in resp.split(b"\r\n", 1)[0]:
        raise RuntimeError(f"CONNECT failed: {resp[:200]!r}")
    return s

CMD = r"""
echo '=== step ==='; grep -rhoE '[0-9]+/627' /root/pronoia/papv_v5_run1.log 2>/dev/null | tail -1
echo '=== log mtime / now ==='; ls -l --time-style=+%H:%M:%S /root/pronoia/papv_v5_run1.log 2>/dev/null | awk '{print $6}'; date +%H:%M:%S
echo '=== reward/kl/grad ==='; grep -oE "\{'loss'.*\}$" /root/pronoia/papv_v5_run1.log 2>/dev/null | tail -1 | grep -oE "'grad_norm': [0-9.]+|'reward': [0-9.]+|'kl': [0-9.e-]+|'learning_rate': [0-9.e-]+"
echo '=== collect rows ==='; wc -l /root/Pronoia/pronoia_run/data_v3/audit/research_cache_team_v4.jsonl 2>/dev/null
echo '=== ckpts ==='; ls -d /root/pronoia/papv_v5_run1/papv_mixed/checkpoint-* 2>/dev/null | tr '\n' ' '; echo
echo '=== train proc ==='; pgrep -af papv_train | head -3
echo '=== collect proc ==='; pgrep -af team_research | head -3
echo '=== gpu ==='; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader 2>/dev/null
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    sock = tunnel()
    c.connect(HOST, port=PORT, username=USER, password=PASS, timeout=60, sock=sock,
              auth_timeout=60, banner_timeout=60)
except Exception as e:
    print("CONNECT_FAIL:", e)
    raise SystemExit(1)

stdin, stdout, stderr = c.exec_command(CMD, timeout=120)
out = stdout.read().decode("utf-8", "replace")
err = stderr.read().decode("utf-8", "replace")
print(out)
if err.strip():
    print("--STDERR--\n" + err[:2000])
c.close()