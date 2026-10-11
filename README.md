# AIFullStackTesting

Pity API 测试平台的 monorepo — 包含后端 (Python FastAPI) 和前端 (React + UmiJS)。

> This is the unified 2026 monorepo for the Pity testing platform. The legacy repositories `pity2025AI` and `pityweb2025Ai` have been merged here starting fresh; commit history from those repos has been intentionally discarded.

## 目录结构

```
.
├── backend/    # Python FastAPI 后端 (port 7777)
├── frontend/   # React + UmiJS 前端 (port 8000, proxies to backend :7777)
└── README.md
```

## 快速开始

```bash
# 后端
cd backend
pip install -r requirements.txt
python main.py

# 前端 (另一终端)
cd frontend
npm install
npm run start:dev
```

更详细的开发命令、架构说明请分别参考:
- [`backend/CLAUDE.md`](backend/CLAUDE.md)
- [`frontend/CLAUDE.md`](frontend/CLAUDE.md)

## License

继承两个子项目原有的许可证(MIT,见 `backend/LICENSE`)。
