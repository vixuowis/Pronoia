"""诊断 config 是否能正确加载 ARK 密钥"""
import sys, os
sys.path.insert(0, '/workspace/backend')
from pathlib import Path

pr = Path('/workspace/backend/app/config.py').resolve().parents[1]
print("config PROJECT_ROOT parent =", pr)   # -> backend
print("parent.parent (should be /workspace) =", pr.parent)
env_file = pr.parent / '.env'
print("/workspace/.env exists:", env_file.exists())

# 直接读 .env
if env_file.exists():
    for line in open(env_file):
        line=line.strip()
        if line.startswith('ARK_API') or line.startswith('MAAS_') or line.startswith('OPENAI'):
            k,v=line.split('=',1) if '=' in line else (line,'')
            print(f"  {k} = {v[:8]}... len={len(v)}")

from app.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, PROJECT_ROOT
print("\nPROJECT_ROOT (from config):", PROJECT_ROOT)
print("LLM_BASE_URL[:60]:", (LLM_BASE_URL or '')[:60])
print("LLM_API_KEY :", ('HAS len='+str(len(LLM_API_KEY))) if LLM_API_KEY else 'EMPTY!!!')
print("LLM_MODEL   :", LLM_MODEL)
