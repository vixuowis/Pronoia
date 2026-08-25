import paramiko
HOST="connect.westd.seetacloud.com"; PORT=12109; USER="root"; PASS="En6mms06iDbK"
import base64, socket
s=socket.create_connection(("127.0.0.1",18080),timeout=20)
s.sendall(f"CONNECT {HOST}:{PORT} HTTP/1.1\r\nHost: {HOST}:{PORT}\r\nProxy-Connection: Keep-Alive\r\n\r\n".encode())
resp=b""
while b"\r\n\r\n" not in resp: resp+=s.recv(4096)
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST,port=PORT,username=USER,password=PASS,timeout=60,sock=s,auth_timeout=60,banner_timeout=60)
# upload qc script, run, get result
sftp=c.open_sftp()
sftp.put("/workspace/_leak.py","/root/_leak.py")
sftp.close()
stdin,stdout,stderr=c.exec_command("/root/miniconda3/bin/python /root/_leak.py",timeout=400)
out=stdout.read().decode("utf-8","replace"); err=stderr.read().decode("utf-8","replace")
print(out[:8000])
if err.strip(): print("--STDERR--\n"+err[:2000])
c.close()
