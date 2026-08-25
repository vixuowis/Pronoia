import paramiko, socket
HOST="connect.westd.seetacloud.com"; PORT=12109; USER="root"; PASS="En6mms06iDbK"
s=socket.create_connection(("127.0.0.1",18080),timeout=20)
s.sendall(f"CONNECT {HOST}:{PORT} HTTP/1.1\r\nHost: {HOST}:{PORT}\r\nProxy-Connection: Keep-Alive\r\n\r\n".encode())
resp=b""
while b"\r\n\r\n" not in resp: resp+=s.recv(4096)
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST,port=PORT,username=USER,password=PASS,timeout=60,sock=s,auth_timeout=60,banner_timeout=60)
CMD=(
 "L=/root/pronoia/papv_v5_run1.log;"
 "echo '=== step ==='; grep -rhoE '[0-9]+/627' $L 2>/dev/null|tail -1;"
 "echo '=== mtime/now ==='; ls -l --time-style=+%H:%M:%S $L 2>/dev/null|awk '{print $6}'; date +%H:%M:%S;"
 "echo '=== last metrics ==='; grep -oE \"\\{'loss'.*\\}$\" $L 2>/dev/null|tail -1|grep -oE \"'grad_norm': [0-9.]+|'reward': [0-9.]+|'kl': [0-9.e-]+|'learning_rate': [0-9.e-]+\";"
 "echo '=== ckpts ==='; ls -d /root/pronoia/papv_v5_run1/papv_mixed/checkpoint-* 2>/dev/null|tr '\\n' ' '; echo;"
 "echo '=== gpu ==='; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader 2>/dev/null;"
 "echo '=== proc ==='; pgrep -af papv_train_remote.py | head -1"
)
stdin,stdout,stderr=c.exec_command(CMD,timeout=120)
print(stdout.read().decode("utf-8","replace"))
print("ERR",stderr.read().decode("utf-8","replace")[:300])
c.close()