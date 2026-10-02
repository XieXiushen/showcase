"""R15-C1 复核：本地视觉服务（llama-server @ 127.0.0.1:8081）现网自检。

用途
    发布前/发布后对一台机器做一次「读数是否落在文章观测区间内」的复核：
    首 token 延迟、端到端耗时、整卡显存峰值、以及模型对已知真值测试图的
    关键判断命中情况（6.71% / P2 / 7 日内回补）。

与文章的关系
    文章《12GB 显卡跑视觉模型》里 G4 组（mmproj 上卡）的本机读数来自
    D:\\ollama\\bench-r14\\result-G4.json：
        加载后整卡 8268 MiB / 峰值 8369 MiB
        冷启动首 token 0.587 s / 热·全量首 token 0.481 s / 缓存命中 0.031 s
        prompt 2322.94 tok/s / decode 116.71 tok/s
    退化组 G6（CUDA DLL 不在 exe 同级，-ngl 99 被忽略）：
        显存恒 1332–1342 MiB、decode 12.70 tok/s、prompt 39.02 tok/s
    本脚本把这些读数当作「验收线」：差得远，先怀疑参数没生效，而不是显卡不行。

前提
    1. llama-server 已启动并监听 8081（本机启动脚本：org\\local-model\\start-vision-server.cmd）
    2. nvidia-smi 在 PATH 里（NVIDIA 驱动自带）
    3. 测试图存在（默认 org\\local-model\\test-image.png，含 4 字段真值）

用法
    python verify_vision.py                       # 用默认图片与默认问题
    python verify_vision.py D:\\path\\img.png       # 换一张图
    python verify_vision.py img.png --max-tokens 400

退出码
    0 = 四项关键真值全部命中；1 = 有未命中（说明模型输出与已知真值不一致，
        先检查图片是否被替换、再检查服务是否真在 GPU 上跑）。
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

SERVER = "http://127.0.0.1:8081"          # 本机视觉服务（llama-server）
HEALTH = SERVER + "/health"
CHAT = SERVER + "/v1/chat/completions"

DEFAULT_IMG = os.path.join(
    os.environ.get("LOCAL_MODEL_DIR", r"C:\Users\Administrator\AppData\Local\hermes\org\local-model"),
    "test-image.png",
)

# 测试图里记录的真值关键判断（road_name 空值率超 5% 阈值 → P2 → 7 日内回补）
KEY_TRUTHS = ("128,430", "6.71%", "P2", "7 日内回补")
PROMPT = "逐行读出图中所有中英文文字，说明表格列名与每行数值，并回答 road_name 的空值率与结论"


def nvidia_used_mib():
    """读整卡 used 显存（MiB）。含桌面常驻，本机桌面常驻约 1331 MiB。"""
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, errors="replace",
    ).stdout.strip().splitlines()
    try:
        return int(out[0].strip())
    except (IndexError, ValueError):
        return -1


def health_ok(timeout=5):
    """服务存活判据：/health 返回 ok。注意：退化到 CPU 时 /health 同样是 ok。"""
    try:
        with urllib.request.urlopen(HEALTH, timeout=timeout) as r:
            return "ok" in r.read().decode("utf-8", "replace")
    except Exception as exc:  # 连接被拒 / 超时都算不健康
        return "ERR:%s" % exc


def conclusion_sentence(answer):
    """从回答里抽出含关键判断的那一句，便于肉眼核对。

    本机模型对这一类问题的输出是按行编号的（1. 字段 / 2. 记录数 ...），
    所以先把换行统一成句号再切句，优先挑同时含「6.71%」与「回补/P2」的那一句。
    """
    segs = [s.strip() for s in answer.replace("\n", "。").split("。") if s.strip()]
    for key in ("回补", "P2"):
        for seg in segs:
            if key in seg and "6.71%" in seg:
                return seg
    for seg in segs:
        if "6.71%" in seg:
            return seg
    return ""


def main():
    args = sys.argv[1:]
    img = DEFAULT_IMG
    max_tokens = 300
    if args and not args[0].startswith("-"):
        img = args[0]
    if "--max-tokens" in args:
        max_tokens = int(args[args.index("--max-tokens") + 1])

    print("[0] 服务健康检查 %s -> %s" % (HEALTH, health_ok()))
    with open(img, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode()
    print("[0] 测试图 %s (%d 字节)  待机显存 %d MiB" % (img, len(b64) * 3 // 4, nvidia_used_mib()))

    payload = {
        "model": "qwen2.5-vl-7b-q4km",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
        ]}],
        "max_tokens": max_tokens,
        "temperature": 0,      # 贪心解码：同一台机器同一次输入应当逐字可复现
        "stream": True,
    }
    req = urllib.request.Request(
        CHAT, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    peak, ttft, t0, text, last_sample = 0, None, time.time(), [], 0.0
    with urllib.request.urlopen(req, timeout=600) as resp:
        for raw in resp:                                  # 流式读取，逐块计时
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                break
            if ttft is None:                              # 第一个数据块即首 token
                ttft = time.time() - t0
            try:
                chunk = json.loads(body)
            except json.JSONDecodeError:
                continue
            for ch in chunk.get("choices", []):
                piece = (ch.get("delta") or {}).get("content") or ""
                if piece:
                    text.append(piece)
            now = time.time()                             # 采样限流：0.5 s 一次，避免拖慢解码
            if now - last_sample >= 0.5:
                last_sample = now
                used = nvidia_used_mib()
                peak = max(peak, used)

    total = time.time() - t0
    peak = max(peak, nvidia_used_mib())
    answer = "".join(text)
    hit = [k for k in KEY_TRUTHS if k in answer]
    miss = [k for k in KEY_TRUTHS if k not in answer]

    print("[1] 首token秒 = %.3f | 端到端秒 = %.2f | 输出字数 = %d" % (ttft or -1, total, len(answer)))
    print("[2] 整卡显存峰值 = %d MiB（含桌面常驻；退化组应停在 1300 MiB 上下）" % peak)
    print("[3] 关键真值命中 %d/%d：%s" % (len(hit), len(KEY_TRUTHS), "、".join(hit)))
    if miss:
        print("    未命中：%s" % "、".join(miss))
    print("[4] 结论句：%s" % (conclusion_sentence(answer) or "(未在回答里找到含 6.71%/P2 的句子)"))
    print("--- 模型回答全文（%d 字） ---" % len(answer))
    print(answer)
    sys.exit(0 if not miss else 1)


if __name__ == "__main__":
    main()
