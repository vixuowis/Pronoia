import paramiko, socket
HOST="connect.westd.seetacloud.com"; PORT=12109; USER="root"; PASS="En6mms06iDbK"
s=socket.create_connection(("127.0.0.1",18080),timeout=20)
s.sendall(f"CONNECT {HOST}:{PORT} HTTP/1.1\r\nHost: {HOST}:{PORT}\r\nProxy-Connection: Keep-Alive\r\n\r\n".encode())
resp=b""
while b"\r\n\r\n" not in resp: resp+=s.recv(4096)
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST,port=PORT,username=USER,password=PASS,timeout=60,sock=s,auth_timeout=60,banner_timeout=60)
cmd = """
echo '=== data_v5 dir ==='; ls -la /root/pronoia/data_v5 2>/dev/null
echo '=== data_v4 dir ==='; ls -la /root/pronoia/data_v4 2>/dev/null
echo '=== data_v3 audit ==='; ls -la /root/Pronoia/pronoia_run/data_v3/audit 2>/dev/null | head -40
echo '=== find jsonl ==='; find /root -maxdepth 4 -name '*.jsonl' 2>/dev/null | grep -iE 'event|label|research' | head -40
"""
stdin,stdout,stderr=c.exec_command(cmd,timeout=90)
print(stdout.read().decode("utf-8","replace"))
print(stderr.read().decode("utf-8","replace")[:1500])
c.close()