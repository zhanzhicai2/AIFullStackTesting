import sys

import uvicorn

from config import Config

# 将原来的
# sys.path.append(__file__)

# 修改为
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if __name__ == "__main__":
    # uvicorn.run(pity, host="0.0.0.0", port=Config.SERVER_PORT, reload=False)
    uvicorn.run("main:pity", host=Config.SERVER_HOST, port=Config.SERVER_PORT, reload=False, forwarded_allow_ips="*")