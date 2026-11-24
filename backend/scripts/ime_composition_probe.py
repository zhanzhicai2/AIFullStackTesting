"""
IME(中文输入法)组合期 Enter 行为探针

**为什么需要这个脚本** —— 前端所有"按 Enter 就提交"的输入框都依赖一条浏览器行为契约:
组合期按 Enter 时, 页面收到的 keydown 带有 `isComposing: true`, 可以据此判断"用户是在选词,
不是在提交"。这条契约**不是规范保证的**, 是各浏览器的实际行为, 且 antd 的
rc-textarea / rc-input **不会替你判断**(`handleKeyDown` 就是 `if (e.key === 'Enter')`)。

**本脚本验证三件事**:
  1. 组合期按 Enter, keydown 的 `key === 'Enter'` 成立 且 `isComposing === true`
     → 证明裸判 `e.key === 'Enter'` 会把"选词"误当成"提交"
  2. 组合期按 Enter, `keyCode` 是 **13 而不是 229**
     → 证明老 guard `e.keyCode === 229` 在 Chromium 上**无效**, 只能用 `e.nativeEvent.isComposing`
  3. 组合期按 Enter **不会往 textarea 插入换行**(带不带 preventDefault 都一样)
     → 证明前端提前 `return` 是安全的, 不需要额外 `preventDefault`
  4. 端到端对照: 同一段输入框代码, 加 guard 的不误触发, 不加 guard 的误触发

**前置**:
  1. 后端 venv 已装 playwright: `uv pip install -r requirements.txt`
  2. **装了 chromium**: `.venv/bin/playwright install chromium`
     ⚠️ 只装 Python 包不装二进制会在启动时报「Executable doesn't exist」

**运行**: `.venv/bin/python scripts/ime_composition_probe.py`

**不依赖数据库 / 不依赖后端服务** —— 纯浏览器行为探针。
"""
import asyncio
import json
import sys

from playwright.async_api import async_playwright

FAILED = []

# 探针页面: 一个 textarea, 分别挂"无 guard"和"有 guard"两个处理器
PAGE = """
<!doctype html>
<html><body>
<textarea id="t" style="width:400px;height:80px"></textarea>
<script>
window.LOG = [];
window.HITS = {unguarded: 0, guarded: 0};

const t = document.getElementById('t');

t.addEventListener('keydown', (e) => {
  window.LOG.push({
    key: e.key,
    keyCode: e.keyCode,
    isComposing: e.isComposing,
    valueAtKeydown: t.value,
  });

  // 模拟 antd 的 rc-textarea / rc-input: 只判 key === 'Enter', 不判 isComposing
  if (e.key === 'Enter') {
    window.HITS.unguarded += 1;          // ← 无 guard: 选词也会误触发
  }

  // 模拟前端修复后的写法: 组合期提前返回
  if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
    window.HITS.guarded += 1;
  }
});
</script>
</body></html>
"""


def check(label, condition, detail=""):
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        FAILED.append(label)


async def press_enter(cdp):
    """派发一次 Enter(组合期会带 isComposing=true)"""
    await cdp.send("Input.dispatchKeyEvent", {
        "type": "rawKeyDown", "key": "Enter", "code": "Enter",
        "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
    })
    await cdp.send("Input.dispatchKeyEvent", {
        "type": "keyUp", "key": "Enter", "code": "Enter",
        "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
    })
    await asyncio.sleep(0.2)


async def probe():
    async with async_playwright() as p:
        # headless shell 没装, 必须走 channel="chromium" 用完整 chromium
        browser = await p.chromium.launch(channel="chromium")
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.set_content(PAGE)
        cdp = await ctx.new_cdp_session(page)

        await page.click("#t")

        # 模拟中文输入法正在拼 "went i"(拼音串, 候选框已弹出)
        await cdp.send("Input.imeSetComposition", {
            "text": "went i", "selectionStart": 6, "selectionEnd": 6,
        })
        await asyncio.sleep(0.15)

        value_before = await page.input_value("#t")
        await press_enter(cdp)
        value_after = await page.input_value("#t")

        log = await page.evaluate("window.LOG")
        hits = await page.evaluate("window.HITS")

        print("\n  组合期按 Enter, 页面收到的 keydown:")
        for e in log:
            print("   ", json.dumps(e, ensure_ascii=False))
        print(f"    组合期输入框内容: {value_before!r} → Enter 后 {value_after!r}")
        print(f"    触发计数: {json.dumps(hits, ensure_ascii=False)}")
        print()

        enter_events = [e for e in log if e["key"] == "Enter"]

        # 1. 组合期确实派发了 key === 'Enter' 的 keydown
        check("组合期按 Enter 会派发 key==='Enter' 的 keydown",
              len(enter_events) == 1,
              f"实际收到 {len(enter_events)} 个")

        if enter_events:
            ev = enter_events[0]
            # 2. 该事件带 isComposing=true —— 这正是前端要判的依据
            check("该 keydown 带 isComposing===true", ev["isComposing"] is True,
                  f"实际 isComposing={ev['isComposing']}")
            # 3. keyCode 是 13, 老 guard(e.keyCode === 229)在 Chromium 上无效
            check("keyCode 是 13(所以 keyCode===229 的老 guard 无效)",
                  ev["keyCode"] == 13, f"实际 {ev['keyCode']}")
            # 4. 组合期拿到的 value 是拼音串, 不是用户选中的汉字
            check("组合期 value 是拼音串(未提交的组合文本)",
                  ev["valueAtKeydown"] == "went i",
                  f"实际 {ev['valueAtKeydown']!r}")

        # 5. 组合期按 Enter 不会插入换行 —— 提前 return 是安全的
        check("组合期按 Enter 不插入换行(提前 return 安全)",
              "\n" not in value_after,
              f"Enter 后 value={value_after!r}")

        # 6. 端到端对照: 无 guard 的会误触发, 有 guard 的不会
        check("无 guard 的处理器在组合期被误触发(这就是 bug)",
              hits["unguarded"] == 1, f"实际 {hits['unguarded']}")
        check("有 isComposing guard 的处理器在组合期不触发(这就是修复)",
              hits["guarded"] == 0, f"实际 {hits['guarded']}")

        await browser.close()


def main():
    print("=" * 66)
    print("IME 组合期 Enter 行为探针")
    print("=" * 66)
    try:
        asyncio.run(probe())
    except Exception as exc:  # noqa: BLE001
        print(f"\n  [FAIL] 探针执行异常: {exc}")
        print("        确认已装 chromium: .venv/bin/playwright install chromium")
        FAILED.append(f"探针执行异常: {exc}")

    print("")
    if FAILED:
        print(f"FAILED {len(FAILED)} 项: {FAILED}")
        sys.exit(1)
    print("全部通过 —— 前端可依赖 isComposing 判别组合期 Enter")


if __name__ == '__main__':
    main()
