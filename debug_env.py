
import os
try:
    with open('config/.env', 'r') as f:
        print(f"✅ Python can read .env! First line: {f.readline().strip()}")
except Exception as e:
    print(f"❌ Python cannot read .env: {e}")
