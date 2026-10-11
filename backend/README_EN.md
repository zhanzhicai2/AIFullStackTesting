[中文文档](README.md)

![png](https://img.shields.io/badge/Python-3.10+-green)
![png](https://img.shields.io/badge/React-18+-blue)
![png](https://img.shields.io/badge/FastApi-green)

## 🎉 Getting Started

1. Clone the repo

```bash
git clone https://github.com/zhanzhicai2/AIFullStackTesting.git
cd AIFullStackTesting/backend
```

2. Install dependencies

```bash
pip install -r requirements.txt
# Can use Tsinghua / Douban mirror for faster install
```

3. Install and start Redis

4. Install and start MySQL

5. Edit `conf/dev.env`

Edit the MySQL and Redis connection info. Redis is optional but disabling it will cause scheduled tasks to repeat (distributed lock implemented via Redis).

6. Start the server

```bash
python main.py
```

7. Register a user

Open `http://localhost:7777` in your browser.

The first registered user becomes `superAdmin` automatically.

## 🌙 Features

- [x] Auth with GitHub OAuth
- [x] Project management with role-based access
- [x] Async FastAPI backend
- [x] Five-case constructors (HTTP / SQL / Redis / Python / nested)
- [x] Parameter extraction (JSONPath / Regex / KV / Status Code)
- [x] Global variables and case data dependencies
- [x] Online HTTP request debugging (Postman-like)
- [x] Online SQL client (multi-database)
- [x] Online Redis client
- [x] Test plan / collection
- [x] Test report HTML templates
- [x] Scheduled test execution (APScheduler + Redis lock)
- [x] Case recording (mitmproxy) and HAR import
- [x] Email / DingTalk notification

## 🙋 Coming soon

- [ ] DataFactory for test data generation
- [ ] HAR / JMX import
- [ ] CI/CD pipeline (in-app)
- [ ] Notification: DingTalk / WeCom
- [ ] Dubbo / gRPC support
- [ ] YApi integration
